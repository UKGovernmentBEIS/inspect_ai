"""Checkpointer skeleton: policy evaluation, no I/O.

Phase 2 scaffolding. ``Checkpointer.tick()`` consults the configured
policy on each agent loop iteration and decides whether the iteration
is a checkpoint moment. Firing is currently a no-op — counters reset,
nothing is written, no event is emitted. Phase 3 replaces ``_fire()``
with the actual checkpoint write.

The active ``Checkpointer`` is exposed via a context variable so that
the module-level :func:`checkpoint` function (used for ``"manual"``
triggers from agent code) can locate it without explicit plumbing.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from types import TracebackType

from ._config import (
    BudgetPercent,
    CheckpointConfig,
    CostInterval,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)

_active: ContextVar["Checkpointer | None"] = ContextVar(
    "inspect_ai_checkpointer", default=None
)

_NOT_YET_IMPLEMENTED = (TokenInterval, CostInterval, BudgetPercent)


class Checkpointer:
    """Per-sample checkpoint policy machinery.

    Construct from a :class:`CheckpointConfig` and use as an async
    context manager inside the agent's loop:

        async with Checkpointer(config) as cp:
            while not done:
                await cp.tick()
                # ...turn body...

    On entry the checkpointer is registered as the active one for the
    current async context, so :func:`checkpoint` can locate it.

    In Phase 2, firing is a no-op (state bookkeeping only). Phase 3
    replaces the fire path with a real write.
    """

    def __init__(self, config: CheckpointConfig) -> None:
        if isinstance(config.policy, _NOT_YET_IMPLEMENTED):
            raise NotImplementedError(
                f"{type(config.policy).__name__} policy is scheduled for Phase 5; "
                "use TimeInterval, TurnInterval, or 'manual' for now."
            )
        self._config = config
        self._token: Token["Checkpointer | None"] | None = None
        self._turns_since_fire: int = 0
        self._last_fire_monotonic: float = time.monotonic()

    async def __aenter__(self) -> "Checkpointer":
        self._token = _active.set(self)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._token is not None
        _active.reset(self._token)
        self._token = None

    async def tick(self) -> None:
        """Invoke at each turn boundary; may fire a checkpoint."""
        if self._config.policy is None:
            return
        self._turns_since_fire += 1
        if self._should_fire():
            await self._fire()

    async def checkpoint(self) -> None:
        """Force a fire regardless of policy (used by manual triggers)."""
        if self._config.policy is None:
            return
        await self._fire()

    def _should_fire(self) -> bool:
        policy = self._config.policy
        if policy is None or policy == "manual":
            return False
        if isinstance(policy, TimeInterval):
            elapsed = time.monotonic() - self._last_fire_monotonic
            return elapsed >= policy.every.total_seconds()
        if isinstance(policy, TurnInterval):
            return self._turns_since_fire >= policy.every
        # __init__ rejects the other variants; this is unreachable.
        raise AssertionError(f"unexpected policy: {policy!r}")

    async def _fire(self) -> None:
        # Phase 2: no-op fire. Phase 3 replaces this with a real
        # checkpoint write. We only reset the counters that gate
        # `_should_fire()` so subsequent ticks measure from this moment.
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()


async def checkpoint() -> None:
    """Manually trigger a checkpoint for the current sample.

    Must be called inside an active :class:`Checkpointer` context — typically
    from inside an agent's loop. Raises :class:`RuntimeError` otherwise.

    Honors a ``None`` policy (no-op) and a ``"manual"`` policy (fires);
    for interval-based policies, a manual call also fires immediately and
    resets the relevant counter.
    """
    cp = _active.get()
    if cp is None:
        raise RuntimeError(
            "checkpoint() called outside an active Checkpointer context."
        )
    await cp.checkpoint()
