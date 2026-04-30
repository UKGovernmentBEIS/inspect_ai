"""Tests for per-attempt subdirectories and sidecar writes."""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai.checkpoint._attempt import attempt_dir_for, write_sidecar
from inspect_ai.checkpoint._layout import CheckpointSidecar


def test_attempt_dir_uses_sample_id_and_epoch() -> None:
    assert (
        attempt_dir_for("/logs/foo.eval.checkpoints", "sample-7", 0)
        == "/logs/foo.eval.checkpoints/sample-7__0"
    )


def test_attempt_dir_accepts_int_sample_id() -> None:
    assert (
        attempt_dir_for("/logs/foo.eval.checkpoints", 42, 1)
        == "/logs/foo.eval.checkpoints/42__1"
    )


async def test_write_sidecar_creates_attempt_dir_and_file(tmp_path: Path) -> None:
    attempt = str(tmp_path / "sample-1__0")

    path = await write_sidecar(
        attempt_dir=attempt, checkpoint_id=1, trigger="turn", turn=3
    )

    assert path == f"{attempt}/ckpt-00001.json"
    assert Path(attempt).is_dir()
    assert Path(path).is_file()


async def test_sidecar_contents_round_trip(tmp_path: Path) -> None:
    attempt = str(tmp_path / "s__0")

    path = await write_sidecar(
        attempt_dir=attempt, checkpoint_id=42, trigger="manual", turn=7
    )

    sidecar = CheckpointSidecar.model_validate_json(Path(path).read_text())
    assert sidecar.checkpoint_id == 42
    assert sidecar.trigger == "manual"
    assert sidecar.turn == 7
    assert sidecar.host_snapshot_id is None
    assert sidecar.sandboxes == {}


async def test_sidecar_filename_zero_padded_for_lexical_sort(tmp_path: Path) -> None:
    attempt = str(tmp_path / "s__0")
    paths = [
        await write_sidecar(
            attempt_dir=attempt, checkpoint_id=cid, trigger="turn", turn=cid
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
    attempt = str(tmp_path / "s__0")
    path = await write_sidecar(
        attempt_dir=attempt, checkpoint_id=1, trigger="turn", turn=1
    )
    raw = Path(path).read_text()
    # Sanity: parses, and indent makes the file multi-line.
    assert json.loads(raw)["checkpoint_id"] == 1
    assert "\n" in raw
