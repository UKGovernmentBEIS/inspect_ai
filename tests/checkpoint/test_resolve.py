"""Unit tests for `merge_checkpoint_configs`."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import pytest

from inspect_ai.dataset import Sample
from inspect_ai.util._checkpoint import (
    ArchiveSnapshots,
    CheckpointConfig,
    CheckpointSampleConfig,
    Manual,
    ResticSnapshots,
    SandboxSnapshotConfig,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from inspect_ai.util._checkpoint.config import (
    DEFAULT_CHECKPOINT_TRIGGER,
    CheckpointDisabled,
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


# --- veto (checkpoint=False) overrides ---------------------------------


@pytest.mark.parametrize(
    "task, sample, eval_",
    [
        pytest.param(
            CheckpointDisabled(),
            None,
            CheckpointConfig(trigger=TurnInterval(every=1)),
            id="task_veto_overrides_eval_enable",
        ),
        pytest.param(
            CheckpointConfig(trigger=TurnInterval(every=1)),
            None,
            CheckpointDisabled(),
            id="eval_veto_overrides_task_enable",
        ),
        pytest.param(
            CheckpointDisabled(),
            CheckpointSampleConfig(trigger=TurnInterval(every=1)),
            None,
            id="task_veto_overrides_sample_config",
        ),
    ],
)
def test_veto_disables_checkpointing(
    task: CheckpointConfig | CheckpointDisabled | None,
    sample: CheckpointSampleConfig | None,
    eval_: CheckpointConfig | CheckpointDisabled | None,
) -> None:
    assert merge_checkpoint_configs(task, sample, eval_) is None


def test_veto_is_per_task_not_eval_wide() -> None:
    # One shared eval enable; a vetoing task resolves to disabled while a
    # non-vetoing task under the same eval config stays enabled. Proves the
    # veto is per-task (no shared-state leak).
    eval_cfg = CheckpointConfig(trigger=TurnInterval(every=1))
    assert merge_checkpoint_configs(CheckpointDisabled(), None, eval_cfg) is None
    assert merge_checkpoint_configs(None, None, eval_cfg) is not None


def test_merge_attaches_task_callbacks() -> None:
    async def on_checkpoint(state: object) -> None:
        return None

    async def on_resume(state: object, attempt: str) -> str:
        return "resumed"

    resolved = merge_checkpoint_configs(
        CheckpointConfig(trigger=Manual()),
        on_checkpoint=on_checkpoint,
        on_resume=on_resume,
    )
    assert resolved is not None
    assert resolved.on_checkpoint is on_checkpoint
    assert resolved.on_resume is on_resume


def test_merge_disabled_ignores_callbacks() -> None:
    async def on_resume(state: object, attempt: str) -> None:
        return None

    # No task/eval config -> checkpointing disabled -> None regardless of callbacks
    assert merge_checkpoint_configs(None, None, None, on_resume=on_resume) is None


def test_task_callbacks_reach_resolved_config() -> None:
    from inspect_ai import Task
    from inspect_ai.dataset import Sample

    async def on_resume(state: object, attempt: str) -> str:
        return "resumed"

    async def on_checkpoint(state: object) -> None:
        return None

    task = Task(
        dataset=[Sample(input="hi")],
        checkpoint=True,
        on_checkpoint=on_checkpoint,
        on_resume=on_resume,
    )
    resolved = merge_checkpoint_configs(
        task.checkpoint,
        None,
        None,
        on_checkpoint=task.on_checkpoint,
        on_resume=task.on_resume,
    )
    assert resolved is not None
    assert resolved.on_checkpoint is on_checkpoint
    assert resolved.on_resume is on_resume


# --- sandbox_paths (capture paths + snapshot strategy selection) -----


def test_sandbox_paths_mixed_values_resolve() -> None:
    """A `sandbox_paths` dict mixes bare path lists and snapshot configs."""
    out = merge_checkpoint_configs(
        CheckpointConfig(
            trigger=Manual(),
            sandbox_paths={
                "default": SandboxSnapshotConfig(
                    paths=["/data"],
                    strategy=ArchiveSnapshots(),
                ),
                "web": SandboxSnapshotConfig(),
                "tools": [],
                "scratch": ["/scratch"],
            },
        )
    )
    assert out is not None
    # Derived paths view: explicit paths verbatim, empty list = opt-out,
    # paths=None omitted (auto-home applies downstream).
    assert out.sandbox_paths == {
        "default": ["/data"],
        "tools": [],
        "scratch": ["/scratch"],
    }
    assert out.sandbox_strategy_config("default") == ArchiveSnapshots()
    assert out.sandbox_strategy_config("web") == ResticSnapshots()
    assert out.sandbox_strategy_config("scratch") == ResticSnapshots()
    # No entry at all → default strategy.
    assert out.sandbox_strategy_config("other") == ResticSnapshots()


def test_sandbox_paths_bare_list_normalizes_into_snapshot_config() -> None:
    out = merge_checkpoint_configs(
        CheckpointConfig(trigger=Manual(), sandbox_paths={"default": ["/workspace"]})
    )
    assert out is not None
    assert out.sandbox_paths == {"default": ["/workspace"]}
    assert out.sandbox_snapshots == {
        "default": SandboxSnapshotConfig(paths=["/workspace"])
    }
    assert out.sandbox_strategy_config("default") == ResticSnapshots()


def test_sandbox_paths_higher_layer_replaces_whole_dict() -> None:
    task = CheckpointConfig(trigger=Manual(), sandbox_paths={"default": ["/workspace"]})
    eval_ = _cfg(
        "sandbox_paths",
        {"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())},
    )
    out = merge_checkpoint_configs(task, None, eval_)
    assert out is not None
    # Whole-value replacement: the eval layer's config wins.
    assert out.sandbox_paths == {}
    assert out.sandbox_strategy_config("default") == ArchiveSnapshots()


# --- strategy selection merges independently of the paths dict --------


def test_sample_paths_override_preserves_task_strategy() -> None:
    """A sample-level bare path list must not reset the task's strategy.

    A bare path list expresses no strategy opinion, so a sample that
    only narrows *what* is captured leaves the task's selection alone.
    """
    task = CheckpointConfig(
        trigger=Manual(),
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())},
    )
    sample = CheckpointSampleConfig(sandbox_paths={"default": ["/data"]})
    out = merge_checkpoint_configs(task, sample)
    assert out is not None
    assert out.sandbox_paths == {"default": ["/data"]}  # sample chose *what*
    assert (
        out.sandbox_strategy_config("default") == ArchiveSnapshots()
    )  # task chose *how*


def test_eval_bare_paths_preserve_task_strategy() -> None:
    """Bare path lists express no strategy opinion at any layer."""
    task = CheckpointConfig(
        trigger=Manual(),
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())},
    )
    eval_ = _cfg("sandbox_paths", {"default": ["/data"]})
    out = merge_checkpoint_configs(task, None, eval_)
    assert out is not None
    assert out.sandbox_paths == {"default": ["/data"]}
    assert out.sandbox_strategy_config("default") == ArchiveSnapshots()


def test_eval_explicit_strategy_overrides_task_strategy() -> None:
    """A higher task/eval layer resets a strategy by setting one explicitly."""
    task = CheckpointConfig(
        trigger=Manual(),
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())},
    )
    eval_ = _cfg(
        "sandbox_paths",
        {"default": SandboxSnapshotConfig(paths=["/data"], strategy=ResticSnapshots())},
    )
    out = merge_checkpoint_configs(task, None, eval_)
    assert out is not None
    assert out.sandbox_paths == {"default": ["/data"]}
    assert out.sandbox_strategy_config("default") == ResticSnapshots()


def test_sample_selects_strategy() -> None:
    """A sample selects the strategy suiting its own workload."""
    task = CheckpointConfig(trigger=Manual(), sandbox_paths={"default": ["/data"]})
    sample = CheckpointSampleConfig(
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())}
    )
    out = merge_checkpoint_configs(task, sample)
    assert out is not None
    assert out.sandbox_strategy_config("default") == ArchiveSnapshots()


def test_sample_strategy_overrides_task_and_yields_to_eval() -> None:
    """Strategy selection resolves per-sandbox at eval > sample > task."""
    task = CheckpointConfig(
        trigger=Manual(),
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ResticSnapshots())},
    )
    sample = CheckpointSampleConfig(
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())}
    )
    out = merge_checkpoint_configs(task, sample)
    assert out is not None
    assert out.sandbox_strategy_config("default") == ArchiveSnapshots()

    eval_ = _cfg(
        "sandbox_paths",
        {"default": SandboxSnapshotConfig(strategy=ResticSnapshots())},
    )
    out = merge_checkpoint_configs(task, sample, eval_)
    assert out is not None
    assert out.sandbox_strategy_config("default") == ResticSnapshots()


def test_checkpoint_config_accepted_at_sample_layer() -> None:
    """CheckpointConfig subclasses the sample config, so Sample accepts it."""
    assert issubclass(CheckpointConfig, CheckpointSampleConfig)
    sample = Sample(input="x", checkpoint=CheckpointConfig(trigger=Manual()))
    assert sample.checkpoint is not None and sample.checkpoint.trigger == Manual()


def test_strategy_applies_to_sandbox_absent_from_winning_paths() -> None:
    """A strategy selection survives a winning paths dict that omits it.

    The sandbox is captured with default paths (home dir) under the
    configured strategy.
    """
    task = CheckpointConfig(
        trigger=Manual(),
        sandbox_paths={"default": SandboxSnapshotConfig(strategy=ArchiveSnapshots())},
    )
    sample = CheckpointSampleConfig(sandbox_paths={"other": ["/x"]})
    out = merge_checkpoint_configs(task, sample)
    assert out is not None
    # Paths view: only the sample's explicit entry ("default" reverts to
    # auto-home, so it has no paths entry).
    assert out.sandbox_paths == {"other": ["/x"]}
    assert out.sandbox_strategy_config("default") == ArchiveSnapshots()
    assert out.sandbox_strategy_config("other") == ResticSnapshots()


def test_strategy_selection_survives_json_round_trip() -> None:
    """The strategy union must not collapse when serialized and re-read.

    The strategy configs are otherwise field-less, so without the `name`
    discriminator both would serialize to `{}` and every pydantic JSON
    round-trip (log recovery, retry-from-log, the viewer) would validate
    back to the first union member, silently converting an explicit
    archive selection into restic.
    """
    for strategy_type in (ArchiveSnapshots, ResticSnapshots):
        sample = Sample(
            input="x",
            checkpoint=CheckpointSampleConfig(
                sandbox_paths={
                    "default": SandboxSnapshotConfig(strategy=strategy_type())
                }
            ),
        )
        back = Sample.model_validate_json(sample.model_dump_json())
        assert back.checkpoint is not None
        assert back.checkpoint.sandbox_paths is not None
        value = back.checkpoint.sandbox_paths["default"]
        assert isinstance(value, SandboxSnapshotConfig)
        assert type(value.strategy) is strategy_type
