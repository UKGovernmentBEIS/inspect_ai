"""Tests for the eval checkpoints dir init."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspect_ai.checkpoint._eval_checkpoints import (
    eval_checkpoints_dir,
    init_eval_checkpoints_dir,
)
from inspect_ai.checkpoint._layout import CheckpointManifest


def test_eval_checkpoints_dir_strips_eval_suffix() -> None:
    assert eval_checkpoints_dir("/logs/foo.eval", None) == "/logs/foo.checkpoints"


def test_eval_checkpoints_dir_passthrough_when_no_eval_suffix() -> None:
    assert eval_checkpoints_dir("/logs/raw_name", None) == "/logs/raw_name.checkpoints"


def test_eval_checkpoints_dir_handles_s3_uri() -> None:
    assert (
        eval_checkpoints_dir("s3://bucket/path/foo.eval", None)
        == "s3://bucket/path/foo.checkpoints"
    )


def test_eval_checkpoints_dir_with_override_root() -> None:
    """Override repoints the parent; the per-eval subdir name is unchanged."""
    assert (
        eval_checkpoints_dir("/logs/foo.eval", "/scratch/ckpts")
        == "/scratch/ckpts/foo.checkpoints"
    )


def test_eval_checkpoints_dir_with_s3_override() -> None:
    assert (
        eval_checkpoints_dir("/logs/foo.eval", "s3://bucket/ckpts")
        == "s3://bucket/ckpts/foo.checkpoints"
    )


async def test_init_creates_dir_and_manifest(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")

    await init_eval_checkpoints_dir(eval_dir, eval_id="eval-001")

    assert Path(eval_dir).is_dir()
    manifest = CheckpointManifest.model_validate_json(
        (Path(eval_dir) / "manifest.json").read_text()
    )
    assert manifest.eval_id == "eval-001"
    assert manifest.layout_version == 1
    assert manifest.engine == "restic"
    assert manifest.restic_password


async def test_init_is_idempotent(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    await init_eval_checkpoints_dir(eval_dir, eval_id="eval-001")
    manifest_path = Path(eval_dir) / "manifest.json"
    original = manifest_path.read_text()

    # Second call must not rewrite the manifest (password must survive).
    await init_eval_checkpoints_dir(eval_dir, eval_id="eval-001")
    assert manifest_path.read_text() == original


async def test_init_rejects_mismatched_eval_id(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    await init_eval_checkpoints_dir(eval_dir, eval_id="eval-001")

    with pytest.raises(RuntimeError, match="different eval"):
        await init_eval_checkpoints_dir(eval_dir, eval_id="eval-002")


async def test_init_creates_parent_dirs(tmp_path: Path) -> None:
    """Eval-dir parent may not exist yet (e.g. nested override root)."""
    eval_dir = str(tmp_path / "nested" / "foo.checkpoints")

    await init_eval_checkpoints_dir(eval_dir, eval_id="eval-001")
    assert Path(eval_dir).is_dir()
    assert (Path(eval_dir) / "manifest.json").is_file()


async def test_manifest_is_valid_json(tmp_path: Path) -> None:
    eval_dir = str(tmp_path / "foo.checkpoints")
    await init_eval_checkpoints_dir(eval_dir, eval_id="eval-001")
    parsed = json.loads((Path(eval_dir) / "manifest.json").read_text())
    assert parsed["eval_id"] == "eval-001"
