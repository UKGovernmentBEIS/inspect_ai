"""Unit tests for `merge_checkpoint_configs`."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import pytest

from inspect_ai.util._checkpoint import (
    CheckpointConfig,
    CheckpointSampleConfig,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from inspect_ai.util._checkpoint.config import (
    DEFAULT_CHECKPOINT_TRIGGER,
    merge_checkpoint_configs,
)

# --- builders -------------------------------------------------------


def _cfg(field: str, value: object) -> CheckpointConfig:
    cfg = CheckpointConfig()
    setattr(cfg, field, value)
    return cfg


def _sample_cfg(field: str, value: object) -> CheckpointSampleConfig:
    cfg = CheckpointSampleConfig()
    setattr(cfg, field, value)
    return cfg


# --- enable predicate + defaults ------------------------------------


def test_no_layers_returns_none() -> None:
    assert merge_checkpoint_configs() is None
    assert merge_checkpoint_configs(None) is None
    assert merge_checkpoint_configs(None, None, None) is None


def test_single_layer_passes_through() -> None:
    out = merge_checkpoint_configs(CheckpointConfig(trigger=TurnInterval(every=5)))
    assert out is not None
    assert out.trigger == TurnInterval(every=5)
    # Defaults are materialized.
    assert out.sandbox_paths == {}
    assert out.retention == "delete"


def test_enabled_without_trigger_defaults_to_500k_tokens() -> None:
    out = merge_checkpoint_configs(CheckpointConfig(checkpoints_location="/tmp"))
    assert out is not None
    assert out.trigger == DEFAULT_CHECKPOINT_TRIGGER == TokenInterval(every=500_000)
    assert out.checkpoints_location == "/tmp"


def test_sample_only_does_not_enable() -> None:
    """A sample-layer config never enables checkpointing — it is ignored."""
    assert (
        merge_checkpoint_configs(
            None, CheckpointSampleConfig(trigger=TurnInterval(every=2)), None
        )
        is None
    )
    # Even with no trigger, a lone sample config is silently ignored (no raise).
    assert merge_checkpoint_configs(None, CheckpointSampleConfig(), None) is None


def test_sample_supplies_trigger_when_eval_has_none() -> None:
    """Eval enables (no trigger); sample customizes the trigger."""
    out = merge_checkpoint_configs(
        task=None,
        sample=CheckpointSampleConfig(trigger=TurnInterval(every=2)),
        eval_=CheckpointConfig(sandbox_paths={"default": ["/workspace"]}),
    )
    assert out is not None
    assert out.trigger == TurnInterval(every=2)  # from sample
    assert out.sandbox_paths == {"default": ["/workspace"]}  # from eval


def test_sample_layer_uses_sample_config_type() -> None:
    """Sample-layer configs are typed CheckpointSampleConfig — no eval-wide fields."""
    sample = CheckpointSampleConfig(trigger=TurnInterval(every=2))
    assert not hasattr(sample, "checkpoints_location")
    assert not hasattr(sample, "retention")


# --- per-field precedence (eval > sample > task) --------------------

# Distinct value per layer for each mergeable field, so the winner is
# unambiguous. The sample value lives on both config types (these fields
# are shared with CheckpointSampleConfig).
_MERGEABLE_VALUES: dict[str, dict[str, object]] = {
    "trigger": {
        "task": TurnInterval(every=5),
        "sample": TurnInterval(every=2),
        "eval": TimeInterval(every=timedelta(minutes=15)),
    },
    "sandbox_paths": {
        "task": {"task": ["/t"]},
        "sample": {"sample": ["/s"]},
        "eval": {"eval": ["/e"]},
    },
    "max_consecutive_failures": {"task": 3, "sample": 10, "eval": 7},
}

# (present layers, winning layer) under precedence eval > sample > task.
# Sample-only is excluded — it never enables, covered separately.
_PRECEDENCE_COMBOS = [
    (("task", "sample", "eval"), "eval"),
    (("task", "sample"), "sample"),
    (("task", "eval"), "eval"),
    (("sample", "eval"), "eval"),
    (("task",), "task"),
    (("eval",), "eval"),
]


@pytest.mark.parametrize("field", list(_MERGEABLE_VALUES))
@pytest.mark.parametrize("present, winner", _PRECEDENCE_COMBOS)
def test_mergeable_field_precedence(
    field: str, present: tuple[str, ...], winner: str
) -> None:
    vals = _MERGEABLE_VALUES[field]
    task = _cfg(field, vals["task"]) if "task" in present else None
    sample = _sample_cfg(field, vals["sample"]) if "sample" in present else None
    eval_ = _cfg(field, vals["eval"]) if "eval" in present else None

    out = merge_checkpoint_configs(task, sample, eval_)
    assert out is not None
    # Distinct keys mean a winning sandbox_paths dict also proves
    # whole-dict replacement (no key-wise merge).
    assert getattr(out, field) == vals[winner]


def test_cross_field_layering() -> None:
    """Different fields resolve from different layers in one merge."""
    task = CheckpointConfig(
        trigger=TurnInterval(every=5),
        sandbox_paths={"default": ["/workspace"]},
        max_consecutive_failures=3,
    )
    sample = CheckpointSampleConfig(max_consecutive_failures=10)
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


# --- eval-wide field precedence (task / eval only) ------------------

_LOCATION = {"task": "/task/ckpt", "eval": "s3://bucket/eval"}


@pytest.mark.parametrize(
    "present, winner",
    [(("task", "eval"), "eval"), (("task",), "task"), (("eval",), "eval")],
)
def test_checkpoints_location_eval_wide_precedence(
    present: tuple[str, ...], winner: str
) -> None:
    task = (
        CheckpointConfig(
            trigger=TurnInterval(every=5), checkpoints_location=_LOCATION["task"]
        )
        if "task" in present
        else None
    )
    eval_ = (
        CheckpointConfig(
            trigger=TurnInterval(every=5), checkpoints_location=_LOCATION["eval"]
        )
        if "eval" in present
        else None
    )
    out = merge_checkpoint_configs(task, None, eval_)
    assert out is not None
    assert out.checkpoints_location == _LOCATION[winner]


@pytest.mark.parametrize(
    "task_r, eval_r",
    [
        ("retain", None),  # task inherits (eval absent)
        ("delete", "retain"),  # eval wins
        (None, "retain"),  # eval only
    ],
)
def test_retention_eval_wide_precedence(
    task_r: Literal["delete", "retain"] | None,
    eval_r: Literal["delete", "retain"] | None,
) -> None:
    # The expected winner is always "retain" (non-default), so a result
    # of "retain" cannot be confused with the materialized default.
    task = (
        CheckpointConfig(trigger=TurnInterval(every=5), retention=task_r)
        if task_r is not None
        else None
    )
    eval_ = (
        CheckpointConfig(trigger=TurnInterval(every=5), retention=eval_r)
        if eval_r is not None
        else None
    )
    out = merge_checkpoint_configs(task, None, eval_)
    assert out is not None
    assert out.retention == "retain"


# --- falsy-but-set edges (None means inherit, not 0 / {}) -----------


def test_explicit_empty_sandbox_paths_overrides_lower() -> None:
    """An explicit empty dict replaces a lower layer's paths (host-only)."""
    out = merge_checkpoint_configs(
        task=CheckpointConfig(
            trigger=TurnInterval(every=5), sandbox_paths={"default": ["/workspace"]}
        ),
        sample=CheckpointSampleConfig(sandbox_paths={}),
    )
    assert out is not None
    assert out.sandbox_paths == {}


def test_zero_max_consecutive_failures_is_set_not_inherited() -> None:
    """``0`` (any failure fatal) is honored, not treated as unset."""
    out = merge_checkpoint_configs(
        task=CheckpointConfig(
            trigger=TurnInterval(every=5), max_consecutive_failures=5
        ),
        sample=CheckpointSampleConfig(max_consecutive_failures=0),
    )
    assert out is not None
    assert out.max_consecutive_failures == 0
