"""Tests for eval checkpoints dir path computation."""

from __future__ import annotations

from inspect_ai.util._checkpoint._layout import eval_checkpoints_dir


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
