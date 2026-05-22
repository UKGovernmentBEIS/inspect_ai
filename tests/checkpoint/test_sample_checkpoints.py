"""Tests for the sample checkpoints dir, sample.json, and sidecar writes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.util._checkpoint._layout import (
    CheckpointDetails,
    CheckpointSample,
    SnapshotDetails,
    ensure_sample_checkpoints_dir,
    ensure_sample_json,
    write_sidecar,
)
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    _read_sample_json,
    _sample_checkpoints_dir,
)
from inspect_ai.util._checkpoint._triggers import CheckpointTriggerKind


def _info(
    snapshot_id: str, size_bytes: int = 0, duration_ms: int = 0
) -> SnapshotDetails:
    return SnapshotDetails(
        snapshot_id=snapshot_id, size_bytes=size_bytes, duration_ms=duration_ms
    )


def _sidecar(
    *,
    checkpoint_id: int,
    trigger: CheckpointTriggerKind,
    turn: int,
    host: SnapshotDetails,
    sandboxes: dict[str, SnapshotDetails] | None = None,
    duration_ms: int = 0,
) -> CheckpointDetails:
    sb = sandboxes or {}
    return CheckpointDetails(
        checkpoint_id=checkpoint_id,
        trigger=trigger,
        turn=turn,
        created_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
        size_bytes=host.size_bytes + sum(s.size_bytes for s in sb.values()),
        host=host,
        sandboxes=sb,
    )


def test_sample_checkpoints_dir_uses_sample_id_and_epoch() -> None:
    assert (
        _sample_checkpoints_dir("/logs/foo.checkpoints", "sample-7", 0)
        == "/logs/foo.checkpoints/sample-7__0"
    )


def test_sample_checkpoints_dir_accepts_int_sample_id() -> None:
    assert (
        _sample_checkpoints_dir("/logs/foo.checkpoints", 42, 1)
        == "/logs/foo.checkpoints/42__1"
    )


async def test_ensure_creates_dir_and_returns_path(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    assert Path(sample_dir).is_dir()
    assert sample_dir == f"{eval_dir}/s1__0"


async def test_ensure_is_idempotent(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    a = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    b = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    assert a == b
    assert Path(a).is_dir()


async def test_ensure_creates_parent_eval_dir(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    assert Path(eval_dir).is_dir()


async def test_ensure_sample_json_mints_password_on_first_call(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    sample = await ensure_sample_json(sample_dir)
    assert sample.restic_password
    assert (Path(sample_dir) / "sample.json").is_file()


async def test_ensure_sample_json_preserves_password_on_second_call(
    tmp_path: Path,
) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    first = await ensure_sample_json(sample_dir)
    second = await ensure_sample_json(sample_dir)
    assert first.restic_password == second.restic_password


async def test_ensure_sample_json_different_samples_get_distinct_passwords(
    tmp_path: Path,
) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    a_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    b_dir = await ensure_sample_checkpoints_dir(eval_dir, "s2", 0)
    a = await ensure_sample_json(a_dir)
    b = await ensure_sample_json(b_dir)
    assert a.restic_password != b.restic_password


async def test_read_sample_json_returns_written_value(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    written = await ensure_sample_json(sample_dir)
    read = await _read_sample_json(sample_dir)
    assert read.restic_password == written.restic_password


async def test_sample_json_round_trip_pydantic(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    sample_dir = await ensure_sample_checkpoints_dir(eval_dir, "s1", 0)
    await ensure_sample_json(sample_dir)
    raw = (Path(sample_dir) / "sample.json").read_text()
    parsed = CheckpointSample.model_validate_json(raw)
    assert parsed.restic_password


async def test_write_sidecar_returns_zero_padded_path(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s1", 0
    )
    path = await write_sidecar(
        sample_checkpoints_dir=sample_dir,
        sidecar=_sidecar(
            checkpoint_id=1,
            trigger="turn",
            turn=3,
            host=_info("snap-1"),
        ),
    )
    assert path == f"{sample_dir}/ckpt-00001.json"
    assert Path(path).is_file()


async def test_sidecar_contents_round_trip(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    path = await write_sidecar(
        sample_checkpoints_dir=sample_dir,
        sidecar=_sidecar(
            checkpoint_id=42,
            trigger="manual",
            turn=7,
            host=_info("snap-42", size_bytes=1000, duration_ms=10),
            sandboxes={"default": _info("sb-42", size_bytes=234, duration_ms=20)},
            duration_ms=99,
        ),
    )
    sidecar = CheckpointDetails.model_validate_json(Path(path).read_text())
    assert sidecar.checkpoint_id == 42
    assert sidecar.trigger == "manual"
    assert sidecar.turn == 7
    assert sidecar.host.snapshot_id == "snap-42"
    assert sidecar.host.duration_ms == 10
    assert sidecar.sandboxes["default"].snapshot_id == "sb-42"
    assert sidecar.size_bytes == 1234  # rolled-up total
    assert sidecar.duration_ms == 99  # whole-cycle


async def test_sidecar_filename_zero_padded_for_lexical_sort(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    paths = [
        await write_sidecar(
            sample_checkpoints_dir=sample_dir,
            sidecar=_sidecar(
                checkpoint_id=cid,
                trigger="turn",
                turn=cid,
                host=_info(f"snap-{cid}"),
            ),
        )
        for cid in (1, 2, 10, 100)
    ]
    names = [Path(p).name for p in paths]
    assert names == sorted(names)
    assert names == [
        "ckpt-00001.json",
        "ckpt-00002.json",
        "ckpt-00010.json",
        "ckpt-00100.json",
    ]


async def test_sidecar_is_pretty_printed_json(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.checkpoints"), "s", 0
    )
    path = await write_sidecar(
        sample_checkpoints_dir=sample_dir,
        sidecar=_sidecar(
            checkpoint_id=1,
            trigger="turn",
            turn=1,
            host=_info("snap-1"),
        ),
    )
    raw = Path(path).read_text()
    assert json.loads(raw)["checkpoint_id"] == 1
    assert "\n" in raw
