"""Tests for eval checkpoints dir path computation."""

from __future__ import annotations

import pytest

from inspect_ai.util._checkpoint import CheckpointConfig, TurnInterval
from inspect_ai.util._checkpoint._layout import eval_checkpoints_dir
from inspect_ai.util._checkpoint._layout.eval_checkpoints_dir import (
    eval_checkpoints_dir_from_config,
)
from inspect_ai.util._checkpoint.config import CheckpointDisabled


def test_eval_checkpoints_dir_strips_eval_suffix() -> None:
    assert eval_checkpoints_dir("/logs/foo.eval", None) == "/logs/foo.checkpoints"


def test_eval_checkpoints_dir_strips_recovered_suffix() -> None:
    assert (
        eval_checkpoints_dir("/logs/foo-recovered.eval", None)
        == "/logs/foo.checkpoints"
    )


def test_eval_checkpoints_dir_passthrough_when_no_eval_suffix() -> None:
    assert eval_checkpoints_dir("/logs/raw_name", None) == "/logs/raw_name.checkpoints"


def test_eval_checkpoints_dir_handles_s3_uri() -> None:
    assert (
        eval_checkpoints_dir("s3://bucket/path/foo.eval", None)
        == "s3://bucket/path/foo.checkpoints"
    )


def test_eval_checkpoints_dir_handles_recovered_s3_uri() -> None:
    assert (
        eval_checkpoints_dir("s3://bucket/path/foo-recovered.eval", None)
        == "s3://bucket/path/foo.checkpoints"
    )


def test_eval_checkpoints_dir_with_override_root() -> None:
    """Override repoints the parent; the per-eval subdir name is unchanged."""
    assert (
        eval_checkpoints_dir("/logs/foo.eval", "/scratch/ckpts")
        == "/scratch/ckpts/foo.checkpoints"
    )


def test_eval_checkpoints_dir_with_recovered_override_root() -> None:
    assert (
        eval_checkpoints_dir("/logs/foo-recovered.eval", "/scratch/ckpts")
        == "/scratch/ckpts/foo.checkpoints"
    )


def test_eval_checkpoints_dir_with_s3_override() -> None:
    assert (
        eval_checkpoints_dir("/logs/foo.eval", "s3://bucket/ckpts")
        == "s3://bucket/ckpts/foo.checkpoints"
    )


def test_eval_checkpoints_dir_strips_trailing_slash_on_override() -> None:
    """A trailing slash on the override must not produce ``//`` in the join.

    S3 honors empty path segments literally, surfacing them as an
    extra "directory" in the console.
    """
    assert (
        eval_checkpoints_dir("/logs/foo.eval", "s3://bucket/ckpts/")
        == "s3://bucket/ckpts/foo.checkpoints"
    )
    assert (
        eval_checkpoints_dir("/logs/foo.eval", "/scratch/ckpts/")
        == "/scratch/ckpts/foo.checkpoints"
    )


# --- eval_checkpoints_dir_from_config veto / no-config cases --------


@pytest.mark.parametrize(
    "task, eval_",
    [
        pytest.param(
            CheckpointDisabled(),
            CheckpointConfig(trigger=TurnInterval(every=1)),
            id="task_veto",
        ),
        pytest.param(
            CheckpointConfig(trigger=TurnInterval(every=1)),
            CheckpointDisabled(),
            id="eval_veto",
        ),
        pytest.param(None, None, id="no_config"),
    ],
)
def test_eval_dir_from_config_returns_none(
    task: CheckpointConfig | CheckpointDisabled | None,
    eval_: CheckpointConfig | CheckpointDisabled | None,
) -> None:
    assert eval_checkpoints_dir_from_config("/logs/run.eval", task, eval_) is None


def test_eval_dir_from_config_enabled_returns_dir() -> None:
    out = eval_checkpoints_dir_from_config(
        "/logs/run.eval", None, CheckpointConfig(trigger=TurnInterval(every=1))
    )
    assert out is not None and "run.checkpoints" in out
