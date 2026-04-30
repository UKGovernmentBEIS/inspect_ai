"""Policy + outer-facade tests for the Checkpointer.

The policy tests drive ``_ActiveCheckpointer`` directly with prepared
dirs, sidestepping the sample-context plumbing. Outer-facade tests
(``Checkpointer(None)``, missing sample context, etc.) and the
end-to-end test exercise the public construction site.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from inspect_ai.checkpoint import (
    CheckpointConfig,
    Checkpointer,
    TimeInterval,
    TurnInterval,
    checkpoint,
)
from inspect_ai.checkpoint._checkpointer import _Checkpointer
from inspect_ai.checkpoint._layout import CheckpointTrigger

# === Policy tests against `_ActiveCheckpointer` directly ====================


@dataclass
class _Dirs:
    checkpoints: str
    working: str


@pytest.fixture
def dirs(tmp_path: Path) -> _Dirs:
    """Pre-create the two sample dirs without going through the facade."""
    checkpoints = tmp_path / "logs/test.eval.checkpoints/s__0"
    working = tmp_path / "cache/checkpoints/test/s__0"
    checkpoints.mkdir(parents=True)
    working.mkdir(parents=True)
    return _Dirs(checkpoints=str(checkpoints), working=str(working))


class _CountingCheckpointer(_Checkpointer):
    """Counts fires on top of the real fire path."""

    fire_count: int = 0

    async def _fire(self, trigger: CheckpointTrigger) -> None:
        await super()._fire(trigger)
        self.fire_count += 1


def _counting(config: CheckpointConfig[Any], dirs: _Dirs) -> _CountingCheckpointer:
    return _CountingCheckpointer(
        config=config,
        sample_checkpoints_dir=dirs.checkpoints,
        sample_working_dir=dirs.working,
    )


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(policy=TurnInterval(every=3)), dirs)
    async with cp:
        for _ in range(9):
            await cp.tick()
    assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(policy=TurnInterval(every=4)), dirs)
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


async def test_time_interval_fires_when_elapsed_exceeds_threshold(dirs: _Dirs) -> None:
    """tick() advances the simulated clock; fires when delta ≥ interval."""
    fake_now = [1000.0]

    def clock() -> float:
        return fake_now[0]

    with patch("inspect_ai.checkpoint._checkpointer.time.monotonic", clock):
        cp = _counting(
            CheckpointConfig(policy=TimeInterval(every=timedelta(seconds=10))), dirs
        )
        async with cp:
            fake_now[0] = 1004.0
            await cp.tick()
            assert cp.fire_count == 0

            fake_now[0] = 1010.0
            await cp.tick()
            assert cp.fire_count == 1

            # immediately again at t=1010 → does not fire (counter just reset)
            await cp.tick()
            assert cp.fire_count == 1

            fake_now[0] = 1025.0
            await cp.tick()
            assert cp.fire_count == 2


# --- manual ---------------------------------------------------------------


async def test_manual_policy_tick_never_fires(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(policy="manual"), dirs)
    async with cp:
        for _ in range(50):
            await cp.tick()
    assert cp.fire_count == 0


async def test_manual_checkpoint_call_fires(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(policy="manual"), dirs)
    async with cp:
        await cp.tick()
        await checkpoint()
        await checkpoint()
    assert cp.fire_count == 2


# === Outer-facade tests =====================================================


@dataclass
class _FakeSample:
    id: int | str | None = 1


@dataclass
class _FakeActiveSample:
    sample: _FakeSample = field(default_factory=_FakeSample)
    epoch: int = 0
    log_location: str = ""  # filled in by the `active_sample` fixture
    eval_id: str | None = "test-eval-001"


@contextmanager
def _patch_sample_active(value: object) -> Iterator[None]:
    with patch("inspect_ai.checkpoint._checkpointer.sample_active", return_value=value):
        yield


@contextmanager
def _patch_cache_dir(tmp_path: Path) -> Iterator[None]:
    def fake_cache_dir(subdir: str | None) -> Path:
        d = tmp_path / "cache" / (subdir or "")
        d.mkdir(parents=True, exist_ok=True)
        return d

    with patch(
        "inspect_ai.checkpoint._working_dir.inspect_cache_dir",
        side_effect=fake_cache_dir,
    ):
        yield


@pytest.fixture
def active_sample(tmp_path: Path) -> Iterator[_FakeActiveSample]:
    """Active sample fixture; redirects on-disk writes under tmp_path."""
    fake = _FakeActiveSample(log_location=str(tmp_path / "logs" / "test.eval"))
    (tmp_path / "logs").mkdir()
    with _patch_sample_active(fake), _patch_cache_dir(tmp_path):
        yield fake


# --- disabled (None config) -----------------------------------------------


async def test_none_config_works_without_active_sample() -> None:
    """`Checkpointer(None)` yields a no-op session; no sample required."""
    with _patch_sample_active(None):
        async with Checkpointer(None) as cp:
            for _ in range(5):
                await cp.tick()
            await cp.checkpoint()


async def test_none_config_does_not_set_active_checkpointer(
    active_sample: _FakeActiveSample,
) -> None:
    """No-op session skips ContextVar setup.

    The free `checkpoint()` from helper code therefore raises rather
    than silently no-op'ing.
    """
    async with Checkpointer(None):
        with pytest.raises(RuntimeError, match="outside an active Checkpointer"):
            await checkpoint()


# --- entering without an active sample -----------------------------------


async def test_aenter_without_active_sample_raises() -> None:
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


# === e2e: outer facade through to disk =====================================


async def test_fire_writes_manifest_and_sidecars(
    active_sample: _FakeActiveSample, tmp_path: Path
) -> None:
    """Driving the outer Checkpointer end-to-end writes destination + working tree."""
    active_sample.sample.id = "s7"
    active_sample.epoch = 2

    async with Checkpointer(CheckpointConfig(policy=TurnInterval(every=2))) as cp:
        await cp.tick()  # turn 1, no fire
        await cp.tick()  # turn 2, fires
        await cp.tick()  # turn 3, no fire
        await cp.tick()  # turn 4, fires

    eval_dir = Path(f"{active_sample.log_location}.checkpoints")
    assert (eval_dir / "manifest.json").is_file()
    sample_dir = eval_dir / "s7__2"
    sidecars = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))
    assert sidecars == ["ckpt-00001.json", "ckpt-00002.json"]

    sample_working = tmp_path / "cache/checkpoints/test/s7__2"
    assert sample_working.is_dir()
    assert (sample_working / "context.json").is_file()
    assert (sample_working / "store.json").is_file()
