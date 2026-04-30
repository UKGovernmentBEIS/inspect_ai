"""Pure policy tests for the Phase 2 Checkpointer skeleton.

No I/O, no event stream — these exercise the decision logic only,
counting how many times ``_fire()`` is invoked under various policies
and externally controlled time/turn schedules.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest

from inspect_ai.checkpoint import (
    BudgetPercent,
    CheckpointConfig,
    Checkpointer,
    CostInterval,
    TimeInterval,
    TokenInterval,
    TurnInterval,
    checkpoint,
)


class _CountingCheckpointer(Checkpointer):
    """Counts fires for assertions; otherwise behaves identically."""

    fire_count: int = 0

    async def _fire(self) -> None:
        await super()._fire()
        self.fire_count += 1


# --- disabled / None policy -----------------------------------------------


async def test_none_policy_never_fires() -> None:
    cp = _CountingCheckpointer(CheckpointConfig())
    async with cp:
        for _ in range(20):
            await cp.tick()
        await checkpoint()
    assert cp.fire_count == 0


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold() -> None:
    cp = _CountingCheckpointer(CheckpointConfig(policy=TurnInterval(every=3)))
    async with cp:
        for _ in range(9):
            await cp.tick()
    assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire() -> None:
    cp = _CountingCheckpointer(CheckpointConfig(policy=TurnInterval(every=4)))
    async with cp:
        for _ in range(3):
            await cp.tick()
        assert cp.fire_count == 0
        await cp.tick()
        assert cp.fire_count == 1
        # counter reset; next fire requires another 4 ticks
        for _ in range(3):
            await cp.tick()
        assert cp.fire_count == 1
        await cp.tick()
        assert cp.fire_count == 2


# --- time-based -----------------------------------------------------------


async def test_time_interval_fires_when_elapsed_exceeds_threshold() -> None:
    """tick() advances the simulated clock; fires when delta ≥ interval."""
    fake_now = [1000.0]

    def clock() -> float:
        return fake_now[0]

    with patch("inspect_ai.checkpoint._checkpointer.time.monotonic", clock):
        # construct inside the patch so __init__ captures the fake clock
        cp = _CountingCheckpointer(
            CheckpointConfig(policy=TimeInterval(every=timedelta(seconds=10)))
        )
        async with cp:
            # at t=1004, 4s elapsed → no fire
            fake_now[0] = 1004.0
            await cp.tick()
            assert cp.fire_count == 0

            # at t=1010, 10s elapsed → fires
            fake_now[0] = 1010.0
            await cp.tick()
            assert cp.fire_count == 1

            # immediately again at t=1010 → does not fire (counter just reset)
            await cp.tick()
            assert cp.fire_count == 1

            # at t=1025, another 15s past last fire → fires again
            fake_now[0] = 1025.0
            await cp.tick()
            assert cp.fire_count == 2


# --- manual ---------------------------------------------------------------


async def test_manual_policy_tick_never_fires() -> None:
    cp = _CountingCheckpointer(CheckpointConfig(policy="manual"))
    async with cp:
        for _ in range(50):
            await cp.tick()
    assert cp.fire_count == 0


async def test_manual_checkpoint_call_fires() -> None:
    cp = _CountingCheckpointer(CheckpointConfig(policy="manual"))
    async with cp:
        await cp.tick()
        await checkpoint()
        await checkpoint()
    assert cp.fire_count == 2


# --- not-yet-implemented policies -----------------------------------------


@pytest.mark.parametrize(
    "policy",
    [
        TokenInterval(every=1000),
        CostInterval(every=1.0),
        BudgetPercent(budget="cost", percent=10.0),
    ],
)
def test_unimplemented_policy_raises(
    policy: TokenInterval | CostInterval | BudgetPercent,
) -> None:
    with pytest.raises(NotImplementedError, match="Phase 5"):
        Checkpointer(CheckpointConfig(policy=policy))


# --- manual trigger outside context ---------------------------------------


async def test_checkpoint_outside_context_raises() -> None:
    with pytest.raises(RuntimeError, match="outside an active Checkpointer"):
        await checkpoint()
