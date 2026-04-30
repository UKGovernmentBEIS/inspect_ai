"""Pure policy tests for the Phase 2 Checkpointer skeleton.

No I/O, no event stream — these exercise the decision logic only,
counting how many times ``_fire()`` is invoked under various policies
and externally controlled time/turn schedules.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
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
from inspect_ai.checkpoint._layout import CheckpointTrigger


class _CountingCheckpointer(Checkpointer):
    """Counts fires for assertions; skips on-disk writes."""

    fire_count: int = 0

    async def _fire(self, trigger: CheckpointTrigger) -> None:
        # Pure policy tests count fires only; the I/O paths live in
        # `test_eval_dir.py` and `test_attempt.py`.
        self._turns_since_fire = 0
        self._last_fire_monotonic = time.monotonic()
        self.fire_count += 1


# Minimal ActiveSample stand-in.  Real ActiveSample has many required
# fields; the Checkpointer only reads four, so a small fake is plenty.
@dataclass
class _FakeSample:
    id: int | str | None = 1


@dataclass
class _FakeActiveSample:
    sample: _FakeSample = field(default_factory=_FakeSample)
    epoch: int = 0
    log_location: str = "/tmp/test.eval"
    eval_id: str | None = "test-eval-001"


@contextmanager
def _patch_sample_active(value: object) -> Iterator[None]:
    with patch("inspect_ai.checkpoint._checkpointer.sample_active", return_value=value):
        yield


@pytest.fixture
def active_sample() -> Iterator[_FakeActiveSample]:
    """Make ``sample_active()`` return a fake for tests that enter a Checkpointer."""
    fake = _FakeActiveSample()
    with _patch_sample_active(fake):
        yield fake


# --- disabled (None config) -----------------------------------------------


async def test_none_config_works_without_active_sample() -> None:
    """`Checkpointer(None)` is a usable no-op; no sample required."""
    cp = _CountingCheckpointer(None)
    with _patch_sample_active(None):
        async with cp:
            for _ in range(5):
                await cp.tick()
            await cp.checkpoint()
    assert cp.fire_count == 0


async def test_none_config_does_not_set_active_checkpointer(
    active_sample: _FakeActiveSample,
) -> None:
    """No-op Checkpointer skips ContextVar setup.

    The free `checkpoint()` function from helper code therefore raises
    rather than silently no-op'ing.
    """
    async with Checkpointer(None):
        with pytest.raises(RuntimeError, match="outside an active Checkpointer"):
            await checkpoint()


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold(
    active_sample: _FakeActiveSample,
) -> None:
    cp = _CountingCheckpointer(CheckpointConfig(policy=TurnInterval(every=3)))
    async with cp:
        for _ in range(9):
            await cp.tick()
    assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire(
    active_sample: _FakeActiveSample,
) -> None:
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


async def test_time_interval_fires_when_elapsed_exceeds_threshold(
    active_sample: _FakeActiveSample,
) -> None:
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


async def test_manual_policy_tick_never_fires(
    active_sample: _FakeActiveSample,
) -> None:
    cp = _CountingCheckpointer(CheckpointConfig(policy="manual"))
    async with cp:
        for _ in range(50):
            await cp.tick()
    assert cp.fire_count == 0


async def test_manual_checkpoint_call_fires(
    active_sample: _FakeActiveSample,
) -> None:
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


# --- entering without an active sample -----------------------------------


async def test_aenter_without_active_sample_raises() -> None:
    """Active policies require a sample context."""
    cp = Checkpointer(CheckpointConfig(policy=TurnInterval(every=1)))
    with (
        _patch_sample_active(None),
        pytest.raises(RuntimeError, match="sample_active.. returned None"),
    ):
        async with cp:
            pass


# --- manual trigger outside context ---------------------------------------


async def test_checkpoint_outside_context_raises() -> None:
    with pytest.raises(RuntimeError, match="outside an active Checkpointer"):
        await checkpoint()


# --- end-to-end fire writes manifest + sidecar ----------------------------


async def test_fire_writes_manifest_and_sidecars(tmp_path: Path) -> None:
    """Driving a real `Checkpointer` end-to-end writes the destination dir + working tree.

    This complements the pure policy tests above; the I/O paths
    themselves are covered in `test_eval_checkpoints.py`,
    `test_sample_checkpoints.py`, and `test_working_dir.py`.
    """
    dest = tmp_path / "dest"
    cache = tmp_path / "cache"
    dest.mkdir()

    def fake_cache_dir(subdir: str | None) -> Path:
        d = cache / (subdir or "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    log = dest / "foo.eval"
    fake = _FakeActiveSample(
        sample=_FakeSample(id="s7"),
        epoch=2,
        log_location=str(log),
        eval_id="eval-xyz",
    )
    cp = Checkpointer(CheckpointConfig(policy=TurnInterval(every=2)))
    with (
        _patch_sample_active(fake),
        patch(
            "inspect_ai.checkpoint._working_dir.inspect_cache_dir",
            side_effect=fake_cache_dir,
        ),
    ):
        async with cp:
            await cp.tick()  # turn 1, no fire
            await cp.tick()  # turn 2, fires
            await cp.tick()  # turn 3, no fire
            await cp.tick()  # turn 4, fires

    eval_dir = Path(f"{log}.checkpoints")
    assert (eval_dir / "manifest.json").is_file()
    sample_dir = eval_dir / "s7__2"
    sidecars = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))
    assert sidecars == ["ckpt-00001.json", "ckpt-00002.json"]

    # Sample working dir mirrors the destination shape under the cache.
    sample_working = cache / "checkpoints/foo/s7__2"
    assert sample_working.is_dir()
    assert (sample_working / "context.json").is_file()
    assert (sample_working / "store.json").is_file()
