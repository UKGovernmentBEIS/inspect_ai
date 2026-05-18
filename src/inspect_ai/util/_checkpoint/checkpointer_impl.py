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
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Any, TypeVar, cast

import anyio
from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from inspect_ai._util._async import tg_collect
from inspect_ai._util.logger import warn_once
from inspect_ai.event._event import Event
from inspect_ai.log import EventsData
from inspect_ai.log._pool import (
    condense_model_event_calls,
    condense_model_event_inputs,
)
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

T = TypeVar("T")


async def build_impl() -> Checkpointer:
    """Build the concrete session for the current sample.

    Reads the resolved :class:`CheckpointConfig` from the active sample
    (set by the harness in :func:`active_sample`). Returns a
    :class:`_NoopCheckpointer` when no sample is active or the active
    sample has no checkpoint config; otherwise pre-ensures on-disk
    dirs and initializes the host + per-sandbox restic repos, then
    returns an :class:`_Checkpointer`.

    Checkpointing is gated off by default while still under
    development — the function returns a no-op session unless the
    ``INSPECT_CHECKPOINTING`` env var is set to ``"1"``.
    """
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

    if os.environ.get("INSPECT_CHECKPOINTING") != "1":
        warn_once(logger, "Checkpointing is still not yet fully implemented")
        return _NoopCheckpointer()

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

    async def tick(self) -> None:
        return None

    async def checkpoint(self) -> None:
        return None

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
    ) -> T:
        return initial_value


class _Checkpointer:
    """Session with all on-disk dependencies pre-ensured."""

    def __init__(
        self,
        config: CheckpointConfig,
        sample_checkpoints_dir: str,
        sample_working_dir: str,
        host_restic: Path,
        restic_password: str,
        resume_state: dict[str, Any] | None = None,
    ) -> None:
        self._config = config
        self._sample_checkpoints_dir = sample_checkpoints_dir
        self._sample_working_dir = sample_working_dir
        self._host_restic = host_restic
        self._host_repo = f"{sample_checkpoints_dir}/host"
        self._restic_password = restic_password
        self._resume_state = resume_state
        self._on_checkpoint_callbacks: dict[str, Callable[[], Any]] = {}
        self._turn = 0
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()
        self._next_checkpoint_id = 1
        # Persisted across fires: each fire processes only the new event slice
        # and appends to these accumulators. Safe because checkpoints fire at
        # turn boundaries, after which prior events are immutable.
        self._condensed_events: list[Event] = []
        self._msg_pool: list[ChatMessage] = []
        self._msg_index: dict[str, int] = {}
        self._call_pool: list[JsonValue] = []
        self._call_index: dict[str, int] = {}
        self._events_consumed = 0

    async def tick(self) -> None:
        self._turn += 1
        self._turns_since_fire += 1
        if self._should_fire():
            await self._fire(self._policy_trigger())

    async def checkpoint(self) -> None:
        await self._fire("manual")

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
    ) -> T:
        if key in self._on_checkpoint_callbacks:
            raise ValueError(
                f"track already registered for key {key!r}; keys must be unique"
            )
        self._on_checkpoint_callbacks[key] = callback
        if self._resume_state is None or key not in self._resume_state:
            return initial_value
        return cast(T, self._resume_state[key])

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

    async def _fire(self, trigger: CheckpointTriggerKind) -> None:
        # Phase 3 (in progress): writes placeholder host context, runs
        # restic backups (host + sandboxes in parallel), then writes
        # the per-checkpoint sidecar.
        cycle_start = time.monotonic()

        state = sample_state()
        if not state:
            raise RuntimeError("Checkpointer must find sample state")
        ts = transcript()
        await self._write_host_context(
            self._sample_working_dir,
            ts.events,
            ts.attachments,
            state.store,
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
        events: Sequence[Event],
        attachments: Mapping[str, str],
        store: Store,
    ) -> None:
        """Write the host context across up to five files.

        - ``events.json`` — condensed events; ModelEvent inputs / calls
          replaced with refs into the pools below.
        - ``events_data.json`` — ``{messages, calls}`` dedup pools.
        - ``attachments.json`` — hash → original-content pool that
          ``ModelEvent.call`` refs (`attachment://<hash>`) point into.
          Captured live by ``Transcript._process_event``; serialized
          here so the snapshot is self-contained.
        - ``store.json`` — Store key/value as a single JSON object.
        - ``agent_state.json`` — agent-defined property bag, written
          only when the agent registered at least one callback via
          :meth:`Checkpointer.track`. Each registered key becomes a
          top-level field in the dict. The agent's conversation
          messages typically live here (e.g. under the ``"messages"``
          key) — the protocol no longer privileges them as a top-level
          file. Presence on disk signals opt-in.
        """
        # Pool ModelEvent input + call messages — the big O(N²) redundancy.
        # We process only the new event slice each fire and append to the
        # accumulators on the session, so total hashing work is O(N) over a
        # sample rather than O(N) per fire. Safe because checkpoints fire at
        # turn boundaries, after which prior events are immutable.
        # Attachments come pre-extracted on the transcript (call payloads
        # >100 chars are rewritten to attachment:// refs as events flow in,
        # with originals in transcript.attachments) — we persist that pool
        # here so resume can resolve the refs.
        new = events[self._events_consumed :]
        if new:
            cond, self._msg_index, new_msgs = condense_model_event_inputs(
                new, len(self._msg_pool), self._msg_index
            )
            self._msg_pool.extend(m for _, m in new_msgs)
            cond, self._call_index, new_calls = condense_model_event_calls(
                cond, len(self._call_pool), self._call_index
            )
            self._call_pool.extend(c for _, c in new_calls)
            self._condensed_events.extend(cond)
            self._events_consumed = len(events)
        events_data = EventsData(messages=self._msg_pool, calls=self._call_pool)
        sample_dir = anyio.Path(sample_working_dir)
        await (sample_dir / "events.json").write_text(
            _json_dump(self._condensed_events)
        )
        await (sample_dir / "events_data.json").write_text(_json_dump(events_data))
        await (sample_dir / "attachments.json").write_text(
            _json_dump(dict(attachments))
        )
        await (sample_dir / "store.json").write_text(_json_dump(store_jsonable(store)))
        if self._on_checkpoint_callbacks:
            agent_state = {
                key: cb() for key, cb in self._on_checkpoint_callbacks.items()
            }
            await (sample_dir / "agent_state.json").write_text(_json_dump(agent_state))

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
