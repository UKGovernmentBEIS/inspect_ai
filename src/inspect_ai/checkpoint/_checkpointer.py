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
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol

from inspect_ai.log._samples import sample_active

from ._config import (
    BudgetPercent,
    CheckpointConfig,
    CostInterval,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from ._layout import CheckpointTrigger
from ._sample_checkpoints import ensure_sample_checkpoints_dir, write_sidecar
from ._working_dir import ensure_sample_working_dir, write_sample_working_dir

_NOT_YET_IMPLEMENTED = (TokenInterval, CostInterval, BudgetPercent)


class CheckpointSession(Protocol):
    """The session yielded by ``async with Checkpointer(...) as cp:``."""

    async def tick(self) -> None:
        """Invoke at each turn boundary; may fire a checkpoint."""
        ...

    async def checkpoint(self) -> None:
        """Force a fire regardless of policy (used by manual triggers)."""
        ...


# Set by `_ActiveCheckpointer.__aenter__`; consumed by the manual
# trigger free function below. Stays unset for `_NoopCheckpointer`,
# which is how a stray `await checkpoint()` from helper code raises
# rather than silently no-op'ing.
_active_checkpointer: ContextVar["_ActiveCheckpointer | None"] = ContextVar(
    "inspect_ai_active_checkpointer", default=None
)


class Checkpointer:
    """Public construction site.

    Picks one of two concrete impls on entry: a no-op session when
    ``config`` is ``None``, or an active session bound to the current
    sample. Either way, the yielded object satisfies
    :class:`CheckpointSession`.
    """

    def __init__(self, config: CheckpointConfig[Any] | None) -> None:
        if config is not None and isinstance(config.policy, _NOT_YET_IMPLEMENTED):
            raise NotImplementedError(
                f"{type(config.policy).__name__} policy is scheduled for Phase 5; "
                "use TimeInterval, TurnInterval, or 'manual' for now."
            )
        self._config = config
        self._impl: _NoopCheckpointer | _ActiveCheckpointer | None = None

    async def __aenter__(self) -> CheckpointSession:
        self._impl = await self._build_impl()
        return await self._impl.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._impl is not None
        await self._impl.__aexit__(exc_type, exc, tb)

    async def _build_impl(self) -> _NoopCheckpointer | _ActiveCheckpointer:
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
        return _ActiveCheckpointer(
            config=self._config,
            sample_checkpoints_dir=sample_checkpoints_dir,
            sample_working_dir=sample_working_dir,
        )


class _NoopCheckpointer:
    """No-op session for ``Checkpointer(None)``."""

    async def __aenter__(self) -> "_NoopCheckpointer":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def tick(self) -> None:
        return None

    async def checkpoint(self) -> None:
        return None


class _ActiveCheckpointer:
    """Session with all on-disk dependencies pre-ensured."""

    def __init__(
        self,
        config: CheckpointConfig[Any],
        sample_checkpoints_dir: str,
        sample_working_dir: Path,
    ) -> None:
        self._config = config
        self._sample_checkpoints_dir = sample_checkpoints_dir
        self._sample_working_dir = sample_working_dir
        self._turn = 0
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()
        self._next_checkpoint_id = 1
        self._reset_token: Token["_ActiveCheckpointer | None"] | None = None

    async def __aenter__(self) -> "_ActiveCheckpointer":
        self._reset_token = _active_checkpointer.set(self)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._reset_token is not None
        _active_checkpointer.reset(self._reset_token)
        self._reset_token = None

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
        await write_sample_working_dir(self._sample_working_dir, self._turn)
        await write_sidecar(
            sample_checkpoints_dir=self._sample_checkpoints_dir,
            checkpoint_id=self._next_checkpoint_id,
            trigger=trigger,
            turn=self._turn,
        )
        self._next_checkpoint_id += 1
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()


async def checkpoint() -> None:
    """Manually trigger a checkpoint for the current sample.

    Must be called inside an active :class:`Checkpointer` context —
    typically from inside an agent's loop. Raises
    :class:`RuntimeError` otherwise.

    Fires immediately regardless of the configured policy; for
    interval-based policies, the relevant counter is reset.
    """
    cp = _active_checkpointer.get()
    if cp is None:
        raise RuntimeError(
            "checkpoint() called outside an active Checkpointer context."
        )
    await cp.checkpoint()
