"""Tests for the eval-level checkpoint directory init."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspect_ai.checkpoint._eval_dir import (
    checkpoint_dir_for_log,
    init_eval_dir,
)
from inspect_ai.checkpoint._layout import CheckpointManifest


def test_checkpoint_dir_for_log_appends_suffix() -> None:
    assert checkpoint_dir_for_log("/logs/foo.eval") == "/logs/foo.eval.checkpoints"


async def test_init_eval_dir_creates_directory_and_manifest(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    log.touch()

    ckpt_dir = await init_eval_dir(str(log), eval_id="eval-001")

    assert ckpt_dir == f"{log}.checkpoints"
    assert Path(ckpt_dir).is_dir()

    manifest_path = Path(ckpt_dir) / "manifest.json"
    manifest = CheckpointManifest.model_validate_json(manifest_path.read_text())
    assert manifest.eval_id == "eval-001"
    assert manifest.layout_version == 1
    assert manifest.engine == "restic"
    assert manifest.restic_password


async def test_init_eval_dir_is_idempotent(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    ckpt_dir = await init_eval_dir(str(log), eval_id="eval-001")
    manifest_path = Path(ckpt_dir) / "manifest.json"
    original = manifest_path.read_text()

    # Second call must not rewrite the manifest (password must survive).
    await init_eval_dir(str(log), eval_id="eval-001")
    assert manifest_path.read_text() == original


async def test_init_eval_dir_rejects_mismatched_eval_id(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    await init_eval_dir(str(log), eval_id="eval-001")

    with pytest.raises(RuntimeError, match="different eval"):
        await init_eval_dir(str(log), eval_id="eval-002")


async def test_init_eval_dir_works_when_log_does_not_exist_yet(
    tmp_path: Path,
) -> None:
    """Logs are created lazily.

    The manifest write must not depend on the `.eval` file already
    existing — only on the parent directory.
    """
    log = tmp_path / "nested" / "foo.eval"
    log.parent.mkdir()

    ckpt_dir = await init_eval_dir(str(log), eval_id="eval-001")
    assert Path(ckpt_dir).is_dir()
    assert (Path(ckpt_dir) / "manifest.json").is_file()


async def test_manifest_is_valid_json(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    ckpt_dir = await init_eval_dir(str(log), eval_id="eval-001")
    raw = (Path(ckpt_dir) / "manifest.json").read_text()
    parsed = json.loads(raw)
    assert parsed["eval_id"] == "eval-001"
