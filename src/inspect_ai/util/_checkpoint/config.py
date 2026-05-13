"""Checkpoint configuration types.

These dataclasses are the public surface that users construct when
configuring checkpointing on a :class:`Sample`, :class:`Task`, or
``eval(...)``. Configs at different levels are combined via per-field
merging — see :func:`merge_checkpoint_configs` in ``_resolve.py``. The
full semantic model is described in
``design/plans/checkpointing-working.md`` §2.

Every field on :class:`CheckpointConfig` defaults to ``None`` so that
"not set at this level" is distinguishable from "explicitly set to a
default value." The merge resolver materializes defaults at the end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal


@dataclass
class TimeInterval:
    """Fire every N of wall-clock time."""

    every: timedelta


@dataclass
class TurnInterval:
    """Fire every N agent turns."""

    every: int


@dataclass
class TokenInterval:
    """Fire every N tokens generated. Not yet implemented (Phase 5)."""

    every: int


@dataclass
class CostInterval:
    """Fire every $N spent. Not yet implemented (Phase 5)."""

    every: float


@dataclass
class BudgetPercent:
    """Fire at percentage milestones of a named budget. Not yet implemented (Phase 5).

    Example: ``BudgetPercent(budget="cost", percent=10)`` fires at 10%, 20%, …
    of the ``cost_limit`` configured on the task or sample.
    """

    budget: Literal["token", "cost", "time", "working"]
    percent: float


CheckpointTrigger = (
    TimeInterval
    | TurnInterval
    | TokenInterval
    | CostInterval
    | BudgetPercent
    | Literal["manual"]
)
"""Checkpoint trigger policy.

- :class:`TimeInterval` — every N of wall-clock time
- :class:`TurnInterval` — every N agent turns
- :class:`TokenInterval` — every N tokens generated (Phase 5)
- :class:`CostInterval` — every $N spent (Phase 5)
- :class:`BudgetPercent` — at percentage milestones of a named budget (Phase 5)
- ``"manual"`` — agent-triggered via :func:`checkpoint`

To disable checkpointing entirely, omit ``checkpoint=...`` at every
level (eval / task / sample).
"""


@dataclass
class Retention:
    """Controls when checkpoint data is deleted."""

    after_eval: Literal["delete", "retain"] = "delete"
    """``"delete"`` (default) removes the checkpoint directory after successful
    eval completion; ``"retain"`` keeps it for later inspection or replay."""


@dataclass
class CheckpointSampleConfig:
    """Checkpoint configuration fields that may be set at the sample layer.

    These fields can be specified on ``Sample(checkpoint=...)`` and are
    also accepted at the task and eval layers (where they participate in
    the per-field merge — precedence: eval > sample > task).

    The fields excluded from this base class — ``checkpoints_dir`` and
    ``retention`` — are eval-wide concerns that the sample layer must
    not influence. They live only on the derived :class:`CheckpointConfig`,
    which is the type used at the task and eval layers.

    See ``design/plans/checkpointing-working.md`` §2.
    """

    trigger: CheckpointTrigger | None = None
    """Checkpoint trigger. See :data:`CheckpointTrigger`. ``None`` means
    "inherit from a lower-priority layer"; the final merged config must
    have a non-None trigger or resolution raises."""

    sandbox_paths: dict[str, list[str]] | None = None
    """Per-sandbox-name list of absolute paths to capture inside the
    sandbox. ``None`` = inherit; ``{}`` (after merge) = host-only
    checkpointing (no sandbox repos)."""

    max_consecutive_failures: int | None = None
    """If set, the sample fails after N consecutive failed checkpoint
    attempts. ``None`` = inherit / unlimited tolerance. ``0`` = any
    failure is fatal."""


@dataclass
class CheckpointConfig(CheckpointSampleConfig):
    """User-facing checkpoint configuration for the task and eval layers.

    Specify on ``Task(checkpoint=...)`` or ``eval(checkpoint=...)``. All
    fields default to ``None`` so that each level can supply a partial
    config; the layers are combined per-field at sample-run time
    (precedence: eval > sample > task).

    Adds the eval-wide fields (``checkpoints_dir``, ``retention``) to
    the sample-permitted base class. Sample-layer configs use the base
    :class:`CheckpointSampleConfig` directly — these fields cannot be
    set per-sample.

    See ``design/plans/checkpointing-working.md`` §2.
    """

    checkpoints_dir: str | None = None
    """Override the parent directory under which the eval checkpoints
    dir lands. ``None`` = sibling of the eval log file. When set,
    inspect places ``<log-base>.checkpoints/`` under this root.
    Supports any fsspec-resolvable path (``s3://``, ``gs://``, plain
    local). Eval-wide — settable only at the task or eval layer."""

    retention: Retention | None = None
    """Controls when checkpoint data is deleted. ``None`` = inherit /
    use the default :class:`Retention` (``after_eval="delete"``).
    Eval-wide — settable only at the task or eval layer."""


def merge_checkpoint_configs(
    task: CheckpointConfig | None = None,
    sample: CheckpointSampleConfig | None = None,
    eval_: CheckpointConfig | None = None,
) -> CheckpointConfig | None:
    """Merge checkpoint config layers across task, sample, and eval.

    Precedence: **eval > sample > task** — the layer closest to the run
    wins on per-field conflicts.

    The sample layer is typed :class:`CheckpointSampleConfig`, so it can
    only contribute to fields shared with that base class
    (``trigger``, ``sandbox_paths``, ``max_consecutive_failures``). The
    eval-wide fields (``checkpoints_dir``, ``retention``) come only
    from the task or eval layers.

    For every field, the highest-priority layer with a non-None value
    wins; lower layers supply defaults that higher layers can override.
    ``sandbox_paths`` is treated as a single value (whole-dict
    replacement), not key-wise merged.

    Returns ``None`` if no layer supplied a config (checkpointing
    disabled). Returns a materialized :class:`CheckpointConfig`
    otherwise — `trigger` is guaranteed non-None and the nullable
    container fields (`sandbox_paths`, `retention`) are filled with
    their canonical defaults.

    Raises ``ValueError`` if at least one layer was supplied but no
    layer set a `trigger`.
    """
    if task is None and sample is None and eval_ is None:
        return None

    trigger: CheckpointTrigger | None = None
    sandbox_paths: dict[str, list[str]] | None = None
    max_consecutive_failures: int | None = None
    for layer in (task, sample, eval_):
        if layer is None:
            continue
        if layer.trigger is not None:
            trigger = layer.trigger
        if layer.sandbox_paths is not None:
            sandbox_paths = layer.sandbox_paths
        if layer.max_consecutive_failures is not None:
            max_consecutive_failures = layer.max_consecutive_failures

    checkpoints_dir: str | None = None
    retention: Retention | None = None
    for layer in (task, eval_):
        if layer is None:
            continue
        if layer.checkpoints_dir is not None:
            checkpoints_dir = layer.checkpoints_dir
        if layer.retention is not None:
            retention = layer.retention

    if trigger is None:
        raise ValueError(
            "checkpoint config provided but no trigger was set at any level"
        )

    return CheckpointConfig(
        trigger=trigger,
        checkpoints_dir=checkpoints_dir,
        sandbox_paths=sandbox_paths if sandbox_paths is not None else {},
        max_consecutive_failures=max_consecutive_failures,
        retention=retention if retention is not None else Retention(),
    )
