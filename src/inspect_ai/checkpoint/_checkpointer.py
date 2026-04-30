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
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from inspect_ai.log._samples import sample_active

from ._config import (
    BudgetPercent,
    CheckpointConfig,
    CostInterval,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from ._eval_checkpoints import init_eval_checkpoints_dir
from ._layout import CheckpointTrigger
from ._sample_checkpoints import write_sidecar
from ._working_dir import write_sample_working_dir

# Scaffolding for ambient lookup of the active Checkpointer from code
# that doesn't hold a Checkpointer reference. Currently consumed only by
# the module-level `checkpoint()` free function below; built-in agents
# (e.g. react) use the direct instance method `Checkpointer.checkpoint()`
# instead, so this var earns its keep only for external custom-agent
# helper code and possible future inspect-internal consumers (e.g. a
# hook payload that wants to ask "is checkpointing active for this
# sample?"). Kept for those forward-looking cases despite no in-tree
# caller today.
_active_checkpointer: ContextVar["Checkpointer | None"] = ContextVar(
    "inspect_ai_active_checkpointer", default=None
)

_NOT_YET_IMPLEMENTED = (TokenInterval, CostInterval, BudgetPercent)


@dataclass(frozen=True)
class _SampleIdentity:
    """Identity captured from `ActiveSample` at `__aenter__` time.

    Used in Phase 3 to compute on-disk checkpoint paths. The retry /
    attempt index is intentionally **not yet** captured here — see the
    note on `Checkpointer.__aenter__` below.
    """

    sample_id: int | str | None
    epoch: int
    log_location: str
    eval_id: str | None


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

    def __init__(self, config: CheckpointConfig[Any] | None) -> None:
        if config is not None and isinstance(config.policy, _NOT_YET_IMPLEMENTED):
            raise NotImplementedError(
                f"{type(config.policy).__name__} policy is scheduled for Phase 5; "
                "use TimeInterval, TurnInterval, or 'manual' for now."
            )
        self._config = config
        # Token from `_active_checkpointer.set(self)` in __aenter__, used
        # by __aexit__ to restore the prior value. Stays None when the
        # Checkpointer is a no-op (config is None) — see __aenter__ for
        # the short-circuit.
        self._reset_token: Token["Checkpointer | None"] | None = None
        self._turn: int = 0
        self._turns_since_fire: int = 0
        self._last_fire_monotonic: float = time.monotonic()
        self._identity: _SampleIdentity | None = None
        # Set on first fire by `_ensure_eval_checkpoints_dir()`;
        # subsequent fires short-circuit the manifest stat/read.
        self._eval_checkpoints_dir: str | None = None
        self._next_checkpoint_id: int = 1

    async def __aenter__(self) -> "Checkpointer":
        # No-op Checkpointer (config is None): skip identity capture and
        # ContextVar setup. `tick()` and `checkpoint()` short-circuit,
        # and a stray `await checkpoint()` from helper code raises (the
        # ContextVar is unset) — that's the desired "you didn't opt in"
        # signal.
        if self._config is None:
            return self

        # Capture sample/epoch/log identity for use by `_fire()` in
        # Phase 3.  Entering an active Checkpointer outside a sample
        # context is a programming error.
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
        self._identity = _SampleIdentity(
            sample_id=active.sample.id,
            epoch=active.epoch,
            log_location=active.log_location,
            eval_id=active.eval_id,
        )
        self._reset_token = _active_checkpointer.set(self)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # No-op Checkpointer never set the ContextVar; nothing to reset.
        if self._reset_token is None:
            return
        _active_checkpointer.reset(self._reset_token)
        self._reset_token = None

    async def tick(self) -> None:
        """Invoke at each turn boundary; may fire a checkpoint."""
        if self._config is None:
            return
        self._turn += 1
        self._turns_since_fire += 1
        if self._should_fire():
            await self._fire(self._policy_trigger())

    async def checkpoint(self) -> None:
        """Force a fire regardless of policy (used by manual triggers)."""
        if self._config is None:
            return
        await self._fire("manual")

    def _should_fire(self) -> bool:
        # Only called after tick()'s None check, so config is non-None.
        assert self._config is not None
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
        assert self._config is not None
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
        # Phase 3 (in progress): the on-disk side currently writes the
        # eval manifest (first fire only), the sample working dir's
        # placeholder context.json/store.json, and a per-checkpoint
        # sidecar. Host repo init, real snapshot ids, and sandbox repos
        # land in subsequent slices.
        await self._ensure_eval_checkpoints_dir()
        assert self._identity is not None
        if self._identity.sample_id is None:
            raise RuntimeError(
                "Checkpointer cannot write a sidecar: ActiveSample.sample.id is None."
            )
        # Materialize the sample working dir (the source restic backs
        # up each cycle). Overwritten in place every fire.
        await write_sample_working_dir(
            self._identity.log_location,
            self._identity.sample_id,
            self._identity.epoch,
            self._turn,
        )
        await write_sidecar(
            log_location=self._identity.log_location,
            sample_id=self._identity.sample_id,
            epoch=self._identity.epoch,
            checkpoint_id=self._next_checkpoint_id,
            trigger=trigger,
            turn=self._turn,
        )
        self._next_checkpoint_id += 1
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()

    async def _ensure_eval_checkpoints_dir(self) -> None:
        if self._eval_checkpoints_dir is not None:
            return
        assert self._identity is not None, "fire path requires captured identity"
        if self._identity.eval_id is None:
            raise RuntimeError(
                "Checkpointer cannot write a manifest: ActiveSample.eval_id is None."
            )
        self._eval_checkpoints_dir = await init_eval_checkpoints_dir(
            self._identity.log_location, self._identity.eval_id
        )


async def checkpoint() -> None:
    """Manually trigger a checkpoint for the current sample.

    Must be called inside an active :class:`Checkpointer` context — typically
    from inside an agent's loop. Raises :class:`RuntimeError` otherwise.

    Fires immediately regardless of the configured policy; for
    interval-based policies, the relevant counter is reset.
    """
    cp = _active_checkpointer.get()
    if cp is None:
        raise RuntimeError(
            "checkpoint() called outside an active Checkpointer context."
        )
    await cp.checkpoint()
