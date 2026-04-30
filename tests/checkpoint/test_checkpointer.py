"""Policy + outer-facade tests for the Checkpointer.

The policy tests drive ``_Checkpointer`` directly with prepared dirs
and call its methods without going through the public facade.
Outer-facade tests cover dispatch, sample-identity validation, and
ContextVar wiring (the public ``Checkpointer`` is what registers the
active session).
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
)
from inspect_ai.checkpoint._checkpointer import _Checkpointer
from inspect_ai.checkpoint._layout import CheckpointTriggerKind
from inspect_ai.checkpoint._restic import ResticBackupSummary


def _fake_summary(checkpoint_id: int) -> ResticBackupSummary:
    return ResticBackupSummary(
        message_type="summary",
        files_new=0,
        files_changed=0,
        files_unmodified=0,
        dirs_new=0,
        dirs_changed=0,
        dirs_unmodified=0,
        data_blobs=0,
        tree_blobs=0,
        data_added=0,
        data_added_packed=0,
        total_files_processed=0,
        total_bytes_processed=0,
        backup_start="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        backup_end="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
        total_duration=0.0,
        snapshot_id=f"fake-snap-{checkpoint_id:05d}",
    )


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
    """Counts fires on top of the real fire path; stubs out restic."""

    fire_count: int = 0

    async def _fire(self, trigger: CheckpointTriggerKind) -> None:
        await super()._fire(trigger)
        self.fire_count += 1

    async def _backup_host(self) -> ResticBackupSummary:
        return _fake_summary(self._next_checkpoint_id)


def _counting(config: CheckpointConfig[Any], dirs: _Dirs) -> _CountingCheckpointer:
    return _CountingCheckpointer(
        config=config,
        sample_checkpoints_dir=dirs.checkpoints,
        sample_working_dir=dirs.working,
        host_restic=Path("/fake/restic"),
        restic_password="test-pwd",
    )


# --- turn-based -----------------------------------------------------------


async def test_turn_interval_fires_at_each_threshold(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger=TurnInterval(every=3)), dirs)
    for _ in range(9):
        await cp.tick()
    assert cp.fire_count == 3


async def test_turn_interval_resets_counter_on_fire(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger=TurnInterval(every=4)), dirs)
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
            CheckpointConfig(trigger=TimeInterval(every=timedelta(seconds=10))), dirs
        )
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
    cp = _counting(CheckpointConfig(trigger="manual"), dirs)
    for _ in range(50):
        await cp.tick()
    assert cp.fire_count == 0


async def test_checkpoint_method_fires(dirs: _Dirs) -> None:
    cp = _counting(CheckpointConfig(trigger="manual"), dirs)
    await cp.tick()
    await cp.checkpoint()
    await cp.checkpoint()
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


@contextmanager
def _patch_restic(tmp_path: Path) -> Iterator[None]:
    """Stub out everything that would actually run restic."""
    fake_binary = tmp_path / "fake_restic"
    fake_binary.write_bytes(b"#!/bin/sh\nexit 0\n")

    async def fake_resolve(platform: object = None) -> Path:
        return fake_binary

    async def fake_init_host_repo(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_run_host_backup(
        *_args: object, **_kwargs: object
    ) -> ResticBackupSummary:
        return _fake_summary(checkpoint_id=1)

    with (
        patch(
            "inspect_ai.checkpoint._checkpointer.resolve_restic",
            side_effect=fake_resolve,
        ),
        patch(
            "inspect_ai.checkpoint._checkpointer.init_host_repo",
            side_effect=fake_init_host_repo,
        ),
        patch(
            "inspect_ai.checkpoint._checkpointer.run_host_backup",
            side_effect=fake_run_host_backup,
        ),
    ):
        yield


@pytest.fixture
def active_sample(tmp_path: Path) -> Iterator[_FakeActiveSample]:
    """Active sample fixture; redirects on-disk writes under tmp_path."""
    fake = _FakeActiveSample(log_location=str(tmp_path / "logs" / "test.eval"))
    (tmp_path / "logs").mkdir()
    with (
        _patch_sample_active(fake),
        _patch_cache_dir(tmp_path),
        _patch_restic(tmp_path),
    ):
        yield fake


# --- disabled (None config) -----------------------------------------------


async def test_none_config_works_without_active_sample() -> None:
    """`Checkpointer(None)` yields a no-op session; no sample required."""
    with _patch_sample_active(None):
        async with Checkpointer(None) as cp:
            for _ in range(5):
                await cp.tick()
            await cp.checkpoint()


# --- entering without an active sample -----------------------------------


async def test_aenter_without_active_sample_raises() -> None:
    cp = Checkpointer(CheckpointConfig(trigger=TurnInterval(every=1)))
    with (
        _patch_sample_active(None),
        pytest.raises(RuntimeError, match="sample_active.. returned None"),
    ):
        async with cp:
            pass


# === e2e: outer facade through to disk =====================================


async def test_fire_writes_manifest_and_sidecars(
    active_sample: _FakeActiveSample, tmp_path: Path
) -> None:
    """Driving the outer Checkpointer end-to-end writes destination + working tree."""
    active_sample.sample.id = "s7"
    active_sample.epoch = 2

    async with Checkpointer(CheckpointConfig(trigger=TurnInterval(every=2))) as cp:
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
