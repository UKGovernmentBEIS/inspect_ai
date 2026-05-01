"""Checkpointer: policy evaluation + on-disk writes.

``async with Checkpointer(config) as cp:`` yields a
:class:`CheckpointSession` on which the agent calls ``tick()`` per
turn (and optionally ``checkpoint()`` for manual triggers). When
``config`` is ``None`` the session is a no-op; otherwise it's an
active session bound to the current sample's identity, with
on-disk dirs pre-ensured before the loop starts.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from contextvars import ContextVar, Token
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai.log._samples import sample_active
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.util import collect
from inspect_ai.util._restic._resolver import resolve_restic
from inspect_ai.util._sandbox.context import sandbox

from ._config import CheckpointConfig, TimeInterval, TurnInterval
from ._eval_checkpoints import eval_checkpoints_dir, read_eval_manifest
from ._layout import CheckpointTriggerKind, SnapshotInfo
from ._restic import (
    ResticBackupSummary,
    egress_sandbox,
    init_host_repo,
    init_sandbox_repo,
    inject_restic,
    run_host_backup,
    run_sandbox_backup,
)
from ._sample_checkpoints import ensure_sample_checkpoints_dir, write_sidecar
from ._working_dir import ensure_sample_working_dir


class CheckpointSession(Protocol):
    """The session yielded by ``async with Checkpointer(...) as cp:``."""

    async def tick(self, messages: Sequence[ChatMessage]) -> None:
        """Invoke at each turn boundary; may fire a checkpoint.

        ``messages`` is the agent's current conversation — the source of
        the messages written into ``context.json`` if this tick fires.
        """
        ...

    async def checkpoint(self) -> None:
        """Force a fire regardless of policy (used by manual triggers).

        Uses the most recent ``messages`` seen by ``tick()``.
        """
        ...


# Set by `Checkpointer.__aenter__` for either impl, so free functions
# (e.g. the manual `checkpoint()` trigger below) get back whichever
# session is active — including the no-op one. Outside any
# `Checkpointer` context, lookups return None.
_active_session: ContextVar[CheckpointSession | None] = ContextVar(
    "inspect_ai_active_checkpoint_session", default=None
)


class Checkpointer:
    """Public construction site.

    Picks one of two concrete impls on entry: a no-op session when
    ``config`` is ``None``, or an active session bound to the current
    sample. Either way, the yielded object satisfies
    :class:`CheckpointSession` and is registered as the active session
    for the current async context.
    """

    def __init__(self, config: CheckpointConfig[Any] | None) -> None:
        self._config = config
        self._impl: CheckpointSession | None = None
        self._reset_token: Token[CheckpointSession | None] | None = None

    async def __aenter__(self) -> CheckpointSession:
        self._impl = await self._build_impl()
        self._reset_token = _active_session.set(self._impl)
        return self._impl

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._reset_token is not None
        _active_session.reset(self._reset_token)
        self._reset_token = None
        self._impl = None

    async def _build_impl(self) -> CheckpointSession:
        if self._config is None:
            return _NoopCheckpointer()

        # Entering an active Checkpointer outside a sample context is a
        # programming error.
        #
        # TODO(checkpointing-phase-3): capture the sample-level retry /
        # attempt index. `ActiveSample` does not currently carry it; the
        # value is published via the `on_sample_attempt_start` hook with
        # `attempt: int` (1-based).  Resolution options are listed in
        # `design/plans/checkpointing-working.md` §1 (re: sample-level
        # retries) — likely we add an `attempt` field to `ActiveSample`
        # so it's symmetric with `epoch`.
        active = sample_active()
        if active is None:
            raise RuntimeError(
                "Checkpointer must be entered within a sample's execution "
                "context; sample_active() returned None."
            )
        if active.eval_id is None:
            raise RuntimeError(
                "Checkpointer cannot initialize: ActiveSample.eval_id is None."
            )
        if active.sample.id is None:
            raise RuntimeError(
                "Checkpointer cannot initialize: ActiveSample.sample.id is None."
            )
        eval_ckpts_dir = eval_checkpoints_dir(
            active.log_location, self._config.checkpoints_dir
        )
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
        for sandbox_name in self._config.sandbox_paths:
            env = sandbox(sandbox_name)
            await inject_restic(env)
            await init_sandbox_repo(env, manifest.restic_password)
        return _Checkpointer(
            config=self._config,
            sample_checkpoints_dir=sample_checkpoints_dir,
            sample_working_dir=sample_working_dir,
            host_restic=host_restic,
            restic_password=manifest.restic_password,
        )


class _NoopCheckpointer:
    """No-op session for ``Checkpointer(None)``."""

    async def tick(self, messages: Sequence[ChatMessage]) -> None:
        return None

    async def checkpoint(self) -> None:
        return None


class _Checkpointer:
    """Session with all on-disk dependencies pre-ensured."""

    def __init__(
        self,
        config: CheckpointConfig[Any],
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
        # Most recent messages seen via tick(); used by both policy
        # fires and manual checkpoint() calls. Stored as a list so the
        # agent can keep mutating its own messages list without
        # affecting our snapshot.
        self._messages: list[ChatMessage] = []

    async def tick(self, messages: Sequence[ChatMessage]) -> None:
        self._messages = list(messages)
        self._turn += 1
        self._turns_since_fire += 1
        if self._should_fire():
            await self._fire(self._policy_trigger())

    async def checkpoint(self) -> None:
        await self._fire("manual")

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

        await self._write_host_context(self._sample_working_dir, self._turn)

        # Host + each sandbox (backup → egress) in parallel. The
        # backup-then-egress pair for a given sandbox is sequential
        # (egress diffs against what backup just wrote), but the pairs
        # are independent across sandboxes and from the host backup.
        # `collect()` adds a transcript span per task.
        sandbox_items = list(self._config.sandbox_paths.items())
        summaries = await collect(
            self._backup_host(),
            *(
                self._backup_and_egress_sandbox(name, paths)
                for name, paths in sandbox_items
            ),
        )
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

    async def _write_host_context(self, sample_working_dir: str, turn: int) -> None:
        """Write the host context (``context.json`` + ``store.json``) for one fire.

        Phase 3 (in progress): ``messages`` are the real conversation
        captured via the most recent ``tick()``; ``events`` and the
        dedup pools (`condense_sample()`-shaped) plus the real ``Store``
        contents land in a subsequent slice.
        """
        sample_dir = anyio.Path(sample_working_dir)
        context = to_jsonable_python(
            {"turn": turn, "messages": self._messages, "events": []},
            exclude_none=True,
            fallback=lambda _: None,
        )
        store_data = to_jsonable_python(
            {"turn": turn}, exclude_none=True, fallback=lambda _: None
        )
        await (sample_dir / "context.json").write_text(json.dumps(context) + "\n")
        await (sample_dir / "store.json").write_text(json.dumps(store_data) + "\n")

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
