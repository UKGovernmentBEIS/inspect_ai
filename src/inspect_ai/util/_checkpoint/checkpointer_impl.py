"""Active checkpoint-session implementation (heavy).

Contains the on-disk write path: parses policy, fires checkpoints,
runs restic backups (host + sandboxes), writes per-checkpoint sidecars.
Imports the parts of ``inspect_ai`` that ultimately reach
``solver._task_state`` and ``dataset.Sample``, so this module must
*not* be imported during initial inspect_ai package load — only at
sample-run time, via :func:`build_session` (called from
``Checkpointer.__aenter__`` in :mod:`_session`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from logging import getLogger
from pathlib import Path

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util._async import tg_collect
from inspect_ai._util.logger import warn_once
from inspect_ai.event._event import Event
from inspect_ai.log._samples import sample_active
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util._restic._resolver import resolve_restic
from inspect_ai.util._sandbox.context import sandbox
from inspect_ai.util._store import Store, store_jsonable

from .checkpointer import Checkpointer
from .config import CheckpointConfig, TimeInterval, TurnInterval
from .eval_checkpoints_dir import eval_checkpoints_dir, read_eval_manifest
from .layout import CheckpointTriggerKind, SnapshotInfo
from .restic import (
    ResticBackupSummary,
    egress_sandbox,
    init_host_repo,
    init_sandbox_repo,
    inject_restic,
    run_host_backup,
    run_sandbox_backup,
)
from .sample_checkpoints_dir import ensure_sample_checkpoints_dir, write_sidecar
from .working_dir import ensure_sample_working_dir

logger = getLogger(__name__)

prevent_use = True


async def build_impl() -> Checkpointer:
    """Build the concrete session for the current sample.

    Reads the resolved :class:`CheckpointConfig` from the active sample
    (set by the harness in :func:`active_sample`). Returns a
    :class:`_NoopCheckpointer` when no sample is active or the active
    sample has no checkpoint config; otherwise pre-ensures on-disk
    dirs and initializes the host + per-sandbox restic repos, then
    returns an :class:`_Checkpointer`.
    """
    if prevent_use:
        warn_once(logger, "Checkpointing is still not yet fully implemented")
        return _NoopCheckpointer()

    # TODO(checkpointing-phase-3): capture the sample-level retry /
    # attempt index. `ActiveSample` does not currently carry it; the
    # value is published via the `on_sample_attempt_start` hook with
    # `attempt: int` (1-based).  Resolution options are listed in
    # `design/plans/checkpointing-working.md` §1 (re: sample-level
    # retries) — likely we add an `attempt` field to `ActiveSample`
    # so it's symmetric with `epoch`.
    active = sample_active()
    if active is None or active.checkpoint is None:
        return _NoopCheckpointer()
    config = active.checkpoint

    if active.eval_id is None:
        raise RuntimeError(
            "Checkpointer cannot initialize: ActiveSample.eval_id is None."
        )
    if active.sample.id is None:
        raise RuntimeError(
            "Checkpointer cannot initialize: ActiveSample.sample.id is None."
        )
    eval_ckpts_dir = eval_checkpoints_dir(active.log_location, config.checkpoints_dir)
    sample_checkpoints_dir = await ensure_sample_checkpoints_dir(
        eval_ckpts_dir, active.sample.id, active.epoch, active.eval_id
    )
    sample_working_dir = await ensure_sample_working_dir(
        active.log_location, active.sample.id, active.epoch
    )
    manifest = await read_eval_manifest(eval_ckpts_dir)
    host_restic = await resolve_restic()
    host_repo = f"{sample_checkpoints_dir}/host"
    await init_host_repo(host_restic, host_repo, manifest.restic_password)
    for sandbox_name in config.sandbox_paths or {}:
        env = sandbox(sandbox_name)
        await inject_restic(env)
        await init_sandbox_repo(env, manifest.restic_password)
    return _Checkpointer(
        config=config,
        sample_checkpoints_dir=sample_checkpoints_dir,
        sample_working_dir=sample_working_dir,
        host_restic=host_restic,
        restic_password=manifest.restic_password,
    )


class _NoopCheckpointer:
    """No-op session for ``Checkpointer()`` with no resolved config."""

    async def tick(self, messages: Sequence[ChatMessage]) -> None:
        return None

    async def checkpoint(self, messages: Sequence[ChatMessage]) -> None:
        return None


class _Checkpointer:
    """Session with all on-disk dependencies pre-ensured."""

    def __init__(
        self,
        config: CheckpointConfig,
        sample_checkpoints_dir: str,
        sample_working_dir: str,
        host_restic: Path,
        restic_password: str,
    ) -> None:
        self._config = config
        self._sample_checkpoints_dir = sample_checkpoints_dir
        self._sample_working_dir = sample_working_dir
        self._host_restic = host_restic
        self._host_repo = f"{sample_checkpoints_dir}/host"
        self._restic_password = restic_password
        self._turn = 0
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()
        self._next_checkpoint_id = 1

    async def tick(self, messages: Sequence[ChatMessage]) -> None:
        self._turn += 1
        self._turns_since_fire += 1
        if self._should_fire():
            await self._fire(self._policy_trigger(), messages)

    async def checkpoint(self, messages: Sequence[ChatMessage]) -> None:
        await self._fire("manual", messages)

    def _should_fire(self) -> bool:
        policy = self._config.trigger
        if policy == "manual":
            return False
        if isinstance(policy, TimeInterval):
            elapsed = time.monotonic() - self._last_fire_monotonic
            return elapsed >= policy.every.total_seconds()
        if isinstance(policy, TurnInterval):
            return self._turns_since_fire >= policy.every
        # __init__ rejects the other variants; this is unreachable.
        raise AssertionError(f"unexpected policy: {policy!r}")

    def _policy_trigger(self) -> CheckpointTriggerKind:
        policy = self._config.trigger
        if isinstance(policy, TimeInterval):
            return "time"
        if isinstance(policy, TurnInterval):
            return "turn"
        # `_should_fire()` returns False for "manual" so we never reach
        # here from `tick()`; the unimplemented variants are blocked at
        # construction time.
        raise AssertionError(f"unexpected policy: {policy!r}")

    async def _fire(
        self, trigger: CheckpointTriggerKind, messages: Sequence[ChatMessage]
    ) -> None:
        # Phase 3 (in progress): writes placeholder host context, runs
        # restic backups (host + sandboxes in parallel), then writes
        # the per-checkpoint sidecar.
        cycle_start = time.monotonic()

        state = sample_state()
        if not state:
            raise RuntimeError("Checkpointer must find sample state")
        await self._write_host_context(
            self._sample_working_dir, messages, transcript().events, state.store
        )

        # Host + each sandbox (backup → egress) in parallel. The
        # backup-then-egress pair for a given sandbox is sequential
        # (egress diffs against what backup just wrote), but the pairs
        # are independent across sandboxes and from the host backup.
        # `tg_collect` takes thunks (zero-arg callables) so coroutines
        # are only created at task-group start time.
        sandbox_items = list((self._config.sandbox_paths or {}).items())
        backup_funcs: list[Callable[[], Awaitable[ResticBackupSummary]]] = [
            self._backup_host,
            *[
                partial(self._backup_and_egress_sandbox, name, paths)
                for name, paths in sandbox_items
            ],
        ]
        summaries = await tg_collect(backup_funcs)
        host_info = _snapshot_info(summaries[0])
        sandbox_infos = {
            name: _snapshot_info(summary)
            for (name, _), summary in zip(sandbox_items, summaries[1:])
        }

        # Cycle duration measured up to the sidecar write — the write
        # itself is the commit point, so its cost lands on the next
        # cycle's clock if anywhere.
        duration_ms = int((time.monotonic() - cycle_start) * 1000)

        await write_sidecar(
            sample_checkpoints_dir=self._sample_checkpoints_dir,
            checkpoint_id=self._next_checkpoint_id,
            trigger=trigger,
            turn=self._turn,
            host=host_info,
            sandboxes=sandbox_infos,
            duration_ms=duration_ms,
        )
        self._next_checkpoint_id += 1
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()

    async def _write_host_context(
        self,
        sample_working_dir: str,
        messages: Sequence[ChatMessage],
        events: Sequence[Event],
        store: Store,
    ) -> None:
        """Write the host context across three files.

        - ``messages.json`` — JSON array of ChatMessage. Append-only in
          practice; restic's content-defined chunking dedups the
          unchanged prefix across snapshots.
        - ``events.json`` — JSON array of Event. Same property.
        - ``store.json`` — Store key/value as a single JSON object.
          Mutates anywhere; doesn't dedup, but it's the smallest file.
        """
        sample_dir = anyio.Path(sample_working_dir)
        await (sample_dir / "messages.json").write_text(_json_dump(messages))
        await (sample_dir / "events.json").write_text(_json_dump(events))
        await (sample_dir / "store.json").write_text(_json_dump(store_jsonable(store)))

    async def _backup_host(self) -> ResticBackupSummary:
        return await run_host_backup(
            self._host_restic,
            self._host_repo,
            self._restic_password,
            self._sample_working_dir,
            self._next_checkpoint_id,
        )

    async def _backup_and_egress_sandbox(
        self, name: str, paths: list[str]
    ) -> ResticBackupSummary:
        env = sandbox(name)
        summary = await run_sandbox_backup(
            env, self._restic_password, paths, self._next_checkpoint_id
        )
        dest_repo = f"{self._sample_checkpoints_dir}/sandboxes/{name}"
        await egress_sandbox(
            env,
            dest_repo=dest_repo,
            password=self._restic_password,
            host_restic=self._host_restic,
            checkpoint_id=self._next_checkpoint_id,
            snapshot_id=summary.snapshot_id,
        )
        return summary


def _snapshot_info(summary: ResticBackupSummary) -> SnapshotInfo:
    return SnapshotInfo(
        snapshot_id=summary.snapshot_id,
        size_bytes=summary.data_added_packed,
        duration_ms=int(summary.total_duration * 1000),
    )


def _json_dump(obj: object) -> str:
    """Serialize ``obj`` to JSON, excluding ``None`` fields, with a trailing newline."""
    return (
        json.dumps(to_jsonable_python(obj, exclude_none=True, fallback=lambda _: None))
        + "\n"
    )
