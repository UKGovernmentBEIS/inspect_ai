"""Checkpointer: policy evaluation + on-disk writes.

``async with Checkpointer(config) as cp:`` yields a
:class:`CheckpointSession` on which the agent calls ``tick()`` per
turn (and optionally ``checkpoint()`` for manual triggers). When
``config`` is ``None`` the session is a no-op; otherwise it's an
active session bound to the current sample's identity, with
on-disk dirs pre-ensured before the loop starts.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from types import TracebackType
from typing import Any, Protocol

import anyio

from inspect_ai.log._samples import sample_active

from ._config import CheckpointConfig, TimeInterval, TurnInterval
from ._layout import CheckpointTrigger
from ._sample_checkpoints import ensure_sample_checkpoints_dir, write_sidecar
from ._working_dir import ensure_sample_working_dir


class CheckpointSession(Protocol):
    """The session yielded by ``async with Checkpointer(...) as cp:``."""

    async def tick(self) -> None:
        """Invoke at each turn boundary; may fire a checkpoint."""
        ...

    async def checkpoint(self) -> None:
        """Force a fire regardless of policy (used by manual triggers)."""
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
        sample_checkpoints_dir = await ensure_sample_checkpoints_dir(
            active.log_location, active.sample.id, active.epoch, active.eval_id
        )
        sample_working_dir = await ensure_sample_working_dir(
            active.log_location, active.sample.id, active.epoch
        )
        return _Checkpointer(
            config=self._config,
            sample_checkpoints_dir=sample_checkpoints_dir,
            sample_working_dir=sample_working_dir,
        )


class _NoopCheckpointer:
    """No-op session for ``Checkpointer(None)``."""

    async def tick(self) -> None:
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
    ) -> None:
        self._config = config
        self._sample_checkpoints_dir = sample_checkpoints_dir
        self._sample_working_dir = sample_working_dir
        self._turn = 0
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()
        self._next_checkpoint_id = 1

    async def tick(self) -> None:
        self._turn += 1
        self._turns_since_fire += 1
        if self._should_fire():
            await self._fire(self._policy_trigger())

    async def checkpoint(self) -> None:
        await self._fire("manual")

    def _should_fire(self) -> bool:
        policy = self._config.policy
        if policy == "manual":
            return False
        if isinstance(policy, TimeInterval):
            elapsed = time.monotonic() - self._last_fire_monotonic
            return elapsed >= policy.every.total_seconds()
        if isinstance(policy, TurnInterval):
            return self._turns_since_fire >= policy.every
        # __init__ rejects the other variants; this is unreachable.
        raise AssertionError(f"unexpected policy: {policy!r}")

    def _policy_trigger(self) -> CheckpointTrigger:
        policy = self._config.policy
        if isinstance(policy, TimeInterval):
            return "time"
        if isinstance(policy, TurnInterval):
            return "turn"
        # `_should_fire()` returns False for "manual" so we never reach
        # here from `tick()`; the unimplemented variants are blocked at
        # construction time.
        raise AssertionError(f"unexpected policy: {policy!r}")

    async def _fire(self, trigger: CheckpointTrigger) -> None:
        # Phase 3 (in progress): writes placeholder content into the
        # sample working dir and a per-checkpoint sidecar. Host repo
        # init + real snapshot ids land in subsequent slices.
        await self._write_host_context(self._sample_working_dir, self._turn)

        await self._backup_host()
        await self._backup_sandboxes()

        await write_sidecar(
            sample_checkpoints_dir=self._sample_checkpoints_dir,
            checkpoint_id=self._next_checkpoint_id,
            trigger=trigger,
            turn=self._turn,
        )
        self._next_checkpoint_id += 1
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()

    async def _write_host_context(self, sample_working_dir: str, turn: int) -> None:
        """Write the host context (``context.json`` + ``store.json``) for one fire.

        Phase 3 (in progress): writes placeholder content carrying the
        current ``turn`` so successive fires produce distinct content.
        Replaced by real condensed-context (`condense_sample()`) and
        ``Store`` serialization in subsequent slices.
        """
        sample_dir = anyio.Path(sample_working_dir)
        await (sample_dir / "context.json").write_text(
            f'{{"turn": {turn}, "messages": [], "events": []}}\n'
        )
        await (sample_dir / "store.json").write_text(f'{{"turn": {turn}}}\n')

    async def _backup_host(self) -> None:
        pass

    async def _backup_sandboxes(self) -> None:
        pass
