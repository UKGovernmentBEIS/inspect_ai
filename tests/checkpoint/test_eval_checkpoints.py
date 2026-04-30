"""Tests for the eval checkpoints dir init."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspect_ai.checkpoint._eval_checkpoints import (
    _eval_checkpoints_dir,
    init_eval_checkpoints_dir,
)
from inspect_ai.checkpoint._layout import CheckpointManifest


def test_eval_checkpoints_dir_appends_suffix() -> None:
    assert _eval_checkpoints_dir("/logs/foo.eval") == "/logs/foo.eval.checkpoints"


async def test_init_creates_dir_and_manifest(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    log.touch()

    eval_dir = await init_eval_checkpoints_dir(str(log), eval_id="eval-001")

    assert eval_dir == f"{log}.checkpoints"
    assert Path(eval_dir).is_dir()

    manifest = CheckpointManifest.model_validate_json(
        (Path(eval_dir) / "manifest.json").read_text()
    )
    assert manifest.eval_id == "eval-001"
    assert manifest.layout_version == 1
    assert manifest.engine == "restic"
    assert manifest.restic_password


async def test_init_is_idempotent(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    eval_dir = await init_eval_checkpoints_dir(str(log), eval_id="eval-001")
    manifest_path = Path(eval_dir) / "manifest.json"
    original = manifest_path.read_text()

    # Second call must not rewrite the manifest (password must survive).
    await init_eval_checkpoints_dir(str(log), eval_id="eval-001")
    assert manifest_path.read_text() == original


async def test_init_rejects_mismatched_eval_id(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    await init_eval_checkpoints_dir(str(log), eval_id="eval-001")

    with pytest.raises(RuntimeError, match="different eval"):
        await init_eval_checkpoints_dir(str(log), eval_id="eval-002")


async def test_init_works_when_log_does_not_exist_yet(tmp_path: Path) -> None:
    """Logs are created lazily.

    The manifest write must not depend on the `.eval` file already
    existing — only on the parent directory.
    """
    log = tmp_path / "nested" / "foo.eval"
    log.parent.mkdir()

    eval_dir = await init_eval_checkpoints_dir(str(log), eval_id="eval-001")
    assert Path(eval_dir).is_dir()
    assert (Path(eval_dir) / "manifest.json").is_file()


async def test_manifest_is_valid_json(tmp_path: Path) -> None:
    log = tmp_path / "foo.eval"
    eval_dir = await init_eval_checkpoints_dir(str(log), eval_id="eval-001")
    parsed = json.loads((Path(eval_dir) / "manifest.json").read_text())
    assert parsed["eval_id"] == "eval-001"
