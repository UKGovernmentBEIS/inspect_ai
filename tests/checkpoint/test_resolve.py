"""Unit tests for `merge_checkpoint_configs`."""

from __future__ import annotations

from datetime import timedelta

import pytest

from inspect_ai.util._checkpoint import (
    CheckpointConfig,
    CheckpointSampleConfig,
    Retention,
    TimeInterval,
    TurnInterval,
)
from inspect_ai.util._checkpoint.config import merge_checkpoint_configs


def test_no_layers_returns_none() -> None:
    assert merge_checkpoint_configs() is None
    assert merge_checkpoint_configs(None) is None
    assert merge_checkpoint_configs(None, None, None) is None


def test_single_layer_passes_through() -> None:
    cfg = CheckpointConfig(trigger=TurnInterval(every=5))
    out = merge_checkpoint_configs(cfg)
    assert out is not None
    assert out.trigger == TurnInterval(every=5)
    # Defaults are materialized.
    assert out.sandbox_paths == {}
    assert out.retention == Retention()


def test_layer_without_trigger_raises() -> None:
    with pytest.raises(ValueError, match="no trigger"):
        merge_checkpoint_configs(CheckpointConfig(checkpoints_location="/tmp"))


def test_sample_layer_uses_sample_config_type() -> None:
    """Sample-layer configs are typed CheckpointSampleConfig — no checkpoints_dir field."""
    sample = CheckpointSampleConfig(trigger=TurnInterval(every=2))
    assert not hasattr(sample, "checkpoints_dir")
    assert not hasattr(sample, "retention")

    out = merge_checkpoint_configs(
        task=CheckpointConfig(
            trigger=TurnInterval(every=5), checkpoints_location="/tmp"
        ),
        sample=sample,
    )
    assert out is not None
    assert out.checkpoints_location == "/tmp"  # from task
    assert out.trigger == TurnInterval(every=2)  # from sample


def test_higher_priority_overrides_trigger() -> None:
    task = CheckpointConfig(trigger=TurnInterval(every=5))
    sample = CheckpointConfig(trigger=TurnInterval(every=2))
    eval_ = CheckpointConfig(trigger=TimeInterval(every=timedelta(minutes=15)))

    # task < sample < eval (left to right priority increases)
    out = merge_checkpoint_configs(task, sample, eval_)
    assert out is not None
    assert out.trigger == TimeInterval(every=timedelta(minutes=15))


def test_sample_overrides_task_when_eval_absent() -> None:
    task = CheckpointConfig(trigger=TurnInterval(every=5))
    sample = CheckpointConfig(trigger=TurnInterval(every=2))
    out = merge_checkpoint_configs(task, sample, None)
    assert out is not None
    assert out.trigger == TurnInterval(every=2)


def test_lower_layer_supplies_default_for_unset_field() -> None:
    """Task provides paths; sample overrides only trigger; merged has both."""
    task = CheckpointConfig(
        trigger=TurnInterval(every=5),
        sandbox_paths={"default": ["/workspace"]},
    )
    sample = CheckpointConfig(trigger=TurnInterval(every=2))
    out = merge_checkpoint_configs(task, sample, None)
    assert out is not None
    assert out.trigger == TurnInterval(every=2)
    assert out.sandbox_paths == {"default": ["/workspace"]}


def test_sandbox_paths_whole_dict_replacement() -> None:
    """Higher layer's sandbox_paths replaces the whole dict (no per-key merge)."""
    task = CheckpointConfig(
        trigger=TurnInterval(every=5),
        sandbox_paths={"default": ["/workspace"]},
    )
    sample = CheckpointConfig(sandbox_paths={"tools": ["/data"]})
    out = merge_checkpoint_configs(task, sample, None)
    assert out is not None
    assert out.sandbox_paths == {"tools": ["/data"]}


def test_per_field_layering() -> None:
    """Different fields can come from different layers."""
    task = CheckpointConfig(
        trigger=TurnInterval(every=5),
        sandbox_paths={"default": ["/workspace"]},
        max_consecutive_failures=3,
    )
    sample = CheckpointConfig(max_consecutive_failures=10)
    eval_ = CheckpointConfig(checkpoints_location="s3://bucket/checkpoints")
    out = merge_checkpoint_configs(task, sample, eval_)
    assert out is not None
    assert out.trigger == TurnInterval(every=5)  # from task
    assert out.sandbox_paths == {"default": ["/workspace"]}  # from task
    assert out.max_consecutive_failures == 10  # from sample
    assert out.checkpoints_location == "s3://bucket/checkpoints"  # from eval


def test_eval_only_with_partial_config_completes_from_task() -> None:
    """Eval CLI overriding cadence alone preserves task's sandbox_paths."""
    task = CheckpointConfig(
        trigger=TurnInterval(every=5),
        sandbox_paths={"default": ["/workspace"]},
    )
    eval_ = CheckpointConfig(trigger=TimeInterval(every=timedelta(minutes=10)))
    out = merge_checkpoint_configs(task, None, eval_)
    assert out is not None
    assert out.trigger == TimeInterval(every=timedelta(minutes=10))
    assert out.sandbox_paths == {"default": ["/workspace"]}


def test_retention_inherits() -> None:
    task = CheckpointConfig(
        trigger=TurnInterval(every=5),
        retention=Retention(after_eval="retain"),
    )
    sample = CheckpointConfig(trigger=TurnInterval(every=2))
    out = merge_checkpoint_configs(task, sample, None)
    assert out is not None
    assert out.retention == Retention(after_eval="retain")
