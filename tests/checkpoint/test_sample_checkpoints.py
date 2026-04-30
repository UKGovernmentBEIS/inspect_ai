"""Tests for the sample checkpoints dir and sidecar writes."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai.checkpoint._layout import CheckpointSidecar
from inspect_ai.checkpoint._sample_checkpoints import (
    _sample_checkpoints_dir,
    ensure_sample_checkpoints_dir,
    write_sidecar,
)


def test_sample_checkpoints_dir_uses_sample_id_and_epoch() -> None:
    assert (
        _sample_checkpoints_dir("/logs/foo.eval", "sample-7", 0)
        == "/logs/foo.eval.checkpoints/sample-7__0"
    )


def test_sample_checkpoints_dir_accepts_int_sample_id() -> None:
    assert (
        _sample_checkpoints_dir("/logs/foo.eval", 42, 1)
        == "/logs/foo.eval.checkpoints/42__1"
    )


async def test_ensure_creates_dir_and_returns_path(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    sample_dir = await ensure_sample_checkpoints_dir(str(log), "s1", 0, "eval-1")
    assert Path(sample_dir).is_dir()
    assert sample_dir == str(tmp_path / "foo.eval.checkpoints" / "s1__0")


async def test_ensure_is_idempotent(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    a = await ensure_sample_checkpoints_dir(str(log), "s1", 0, "eval-1")
    b = await ensure_sample_checkpoints_dir(str(log), "s1", 0, "eval-1")
    assert a == b
    assert Path(a).is_dir()


async def test_write_sidecar_returns_zero_padded_path(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.eval"), "s1", 0, "eval-1"
    )
    path = await write_sidecar(
        sample_checkpoints_dir=sample_dir,
        checkpoint_id=1,
        trigger="turn",
        turn=3,
    )
    assert path == f"{sample_dir}/ckpt-00001.json"
    assert Path(path).is_file()


async def test_sidecar_contents_round_trip(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.eval"), "s", 0, "eval-1"
    )
    path = await write_sidecar(
        sample_checkpoints_dir=sample_dir,
        checkpoint_id=42,
        trigger="manual",
        turn=7,
    )
    sidecar = CheckpointSidecar.model_validate_json(Path(path).read_text())
    assert sidecar.checkpoint_id == 42
    assert sidecar.trigger == "manual"
    assert sidecar.turn == 7
    assert sidecar.host_snapshot_id is None
    assert sidecar.sandboxes == {}


async def test_sidecar_filename_zero_padded_for_lexical_sort(tmp_path: Path) -> None:
    sample_dir = await ensure_sample_checkpoints_dir(
        str(tmp_path / "foo.eval"), "s", 0, "eval-1"
    )
    paths = [
        await write_sidecar(
            sample_checkpoints_dir=sample_dir,
            checkpoint_id=cid,
            trigger="turn",
            turn=cid,
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
        str(tmp_path / "foo.eval"), "s", 0, "eval-1"
    )
    path = await write_sidecar(
        sample_checkpoints_dir=sample_dir,
        checkpoint_id=1,
        trigger="turn",
        turn=1,
    )
    raw = Path(path).read_text()
    assert json.loads(raw)["checkpoint_id"] == 1
    assert "\n" in raw
