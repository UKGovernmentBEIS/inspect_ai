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
class CheckpointConfig:
    """User-facing checkpoint configuration.

    Specify on ``Sample(checkpoint=...)``, ``Task(checkpoint=...)``, or
    ``eval(checkpoint=...)``. All fields default to ``None`` so that
    each level can supply a partial config; the layers are combined
    per-field at sample-run time (precedence: eval > sample > task).

    Construct a config at the level that "owns" each value:
    - **Task**: defaults common to every sample (typical trigger,
      sandbox paths).
    - **Sample**: per-row overrides (e.g. a particular sample needs a
      tighter cadence or a different captured path).
    - **Eval / CLI**: run-level overrides (e.g. operator switches
      cadence or destination for one run).

    See ``design/plans/checkpointing-working.md`` §2.
    """

    trigger: CheckpointTrigger | None = None
    """Checkpoint trigger. See :data:`CheckpointTrigger`. ``None`` means
    "inherit from a lower-priority layer"; the final merged config must
    have a non-None trigger or resolution raises."""

    checkpoints_dir: str | None = None
    """Override the parent directory under which the eval checkpoints
    dir lands. ``None`` = sibling of the eval log file. When set,
    inspect places ``<log-base>.checkpoints/`` under this root.
    Supports any fsspec-resolvable path (``s3://``, ``gs://``, plain
    local). The sample layer is permitted to set this field, but
    cannot **override** a value already set at the task or eval
    layer — see :func:`merge_checkpoint_configs`."""

    sandbox_paths: dict[str, list[str]] | None = None
    """Per-sandbox-name list of absolute paths to capture inside the
    sandbox. ``None`` = inherit; ``{}`` (after merge) = host-only
    checkpointing (no sandbox repos)."""

    max_consecutive_failures: int | None = None
    """If set, the sample fails after N consecutive failed checkpoint
    attempts. ``None`` = inherit / unlimited tolerance. ``0`` = any
    failure is fatal."""

    retention: Retention | None = None
    """Controls when checkpoint data is deleted. ``None`` = inherit /
    use the default :class:`Retention` (``after_eval="delete"``)."""


def merge_checkpoint_configs(
    task: CheckpointConfig | None = None,
    sample: CheckpointConfig | None = None,
    eval_: CheckpointConfig | None = None,
) -> CheckpointConfig | None:
    """Merge :class:`CheckpointConfig` layers across task, sample, and eval.

    Precedence: **eval > sample > task** — the layer closest to the run
    wins on per-field conflicts.

    For every field, the highest-priority layer with a non-None value
    wins; lower layers supply defaults that higher layers can override.
    ``sandbox_paths`` is treated as a single value (whole-dict
    replacement), not key-wise merged.

    ``checkpoints_dir`` is the one exception to per-field overriding:
    the sample layer is not permitted to **override** it. A
    sample-layer value is allowed when it would not change the
    resolved value — i.e. when the task and eval layers don't set
    ``checkpoints_dir`` (nothing to override), or when the sample's
    value matches what the task / eval layers already resolve to (a
    redundant restatement). A sample-layer value that differs from
    a non-None task or eval value raises ``ValueError``.

    Returns ``None`` if no layer supplied a config (checkpointing
    disabled). Returns a materialized :class:`CheckpointConfig`
    otherwise — `trigger` is guaranteed non-None and the nullable
    container fields (`sandbox_paths`, `retention`) are filled with
    their canonical defaults.

    Raises ``ValueError`` if at least one layer was supplied but no
    layer set a `trigger`, or if the sample layer's ``checkpoints_dir``
    would override the task / eval layers' value.
    """
    if sample is not None and sample.checkpoints_dir is not None:
        baseline = (
            eval_.checkpoints_dir
            if eval_ is not None and eval_.checkpoints_dir is not None
            else (task.checkpoints_dir if task is not None else None)
        )
        if baseline is not None and sample.checkpoints_dir != baseline:
            raise ValueError(
                "sample-level checkpoints_dir cannot override the task / eval "
                f"value (sample={sample.checkpoints_dir!r}, baseline={baseline!r})"
            )

    provided = [c for c in (task, sample, eval_) if c is not None]
    if not provided:
        return None

    trigger = None
    checkpoints_dir = None
    sandbox_paths: dict[str, list[str]] | None = None
    max_consecutive_failures = None
    retention: Retention | None = None

    for layer in provided:
        if layer.trigger is not None:
            trigger = layer.trigger
        if layer.checkpoints_dir is not None:
            checkpoints_dir = layer.checkpoints_dir
        if layer.sandbox_paths is not None:
            sandbox_paths = layer.sandbox_paths
        if layer.max_consecutive_failures is not None:
            max_consecutive_failures = layer.max_consecutive_failures
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
