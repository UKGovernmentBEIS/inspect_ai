"""Tests for `checkpoint=True` in the Python API.

Passing ``True`` to a ``checkpoint=`` argument is the Python-API
equivalent of the bare ``--checkpoint`` CLI flag: it enables
checkpointing without pinning a trigger, and the concrete default
(``TokenInterval(every=500_000)``) is resolved per-sample by
``merge_checkpoint_configs``.
"""

from __future__ import annotations

import pytest

from inspect_ai import Task
from inspect_ai._eval.task.task import task_with
from inspect_ai.util._checkpoint import TokenInterval, TurnInterval
from inspect_ai.util._checkpoint.config import (
    CheckpointConfig,
    merge_checkpoint_configs,
    normalize_checkpoint,
)
from inspect_ai.util._checkpoint.parse_cli import parse_checkpoint


def test_normalize_true_enables_without_trigger() -> None:
    assert normalize_checkpoint(True) == CheckpointConfig(trigger=None)


@pytest.mark.parametrize("value", [False, None])
def test_normalize_falsey_disables(value: bool | None) -> None:
    assert normalize_checkpoint(value) is None


def test_normalize_passes_config_through_unchanged() -> None:
    cfg = CheckpointConfig(trigger=TurnInterval(every=3))
    assert normalize_checkpoint(cfg) is cfg


def test_true_matches_bare_cli_flag() -> None:
    """`checkpoint=True` and the bare `--checkpoint` flag resolve identically."""
    assert normalize_checkpoint(True) == parse_checkpoint("default")


def test_true_resolves_to_500k_tokens() -> None:
    out = merge_checkpoint_configs(eval_=normalize_checkpoint(True))
    assert out is not None
    assert out.trigger == TokenInterval(every=500_000)


def test_true_defers_trigger_to_sample() -> None:
    """`True` enables without pinning a trigger, so a sample can still win."""
    from inspect_ai.util._checkpoint import CheckpointSampleConfig

    out = merge_checkpoint_configs(
        eval_=normalize_checkpoint(True),
        sample=CheckpointSampleConfig(trigger=TurnInterval(every=2)),
    )
    assert out is not None
    assert out.trigger == TurnInterval(every=2)


def test_task_checkpoint_true_enables() -> None:
    task = Task(checkpoint=True)
    assert task.checkpoint == CheckpointConfig(trigger=None)
    out = merge_checkpoint_configs(task=task.checkpoint)
    assert out is not None
    assert out.trigger == TokenInterval(every=500_000)


@pytest.mark.parametrize("value", [False, None])
def test_task_checkpoint_falsey_disables(value: bool | None) -> None:
    assert Task(checkpoint=value).checkpoint is None


def test_task_with_checkpoint_true_enables() -> None:
    task = task_with(Task(), checkpoint=True)
    assert task.checkpoint == CheckpointConfig(trigger=None)


def test_task_with_checkpoint_omitted_leaves_unchanged() -> None:
    original = CheckpointConfig(trigger=TurnInterval(every=4))
    task = task_with(Task(checkpoint=original))
    assert task.checkpoint == original
