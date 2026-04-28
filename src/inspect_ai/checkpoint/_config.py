"""Checkpoint configuration types.

These dataclasses are the public surface that agent authors construct
when wiring checkpointing into their loop. The full semantic model is
described in ``design/plans/checkpointing-working.md`` §2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


CheckpointPolicy = (
    TimeInterval
    | TurnInterval
    | TokenInterval
    | CostInterval
    | BudgetPercent
    | Literal["manual"]
    | None
)
"""Checkpoint trigger policy.

- :class:`TimeInterval` — every N of wall-clock time
- :class:`TurnInterval` — every N agent turns
- :class:`TokenInterval` — every N tokens generated (Phase 5)
- :class:`CostInterval` — every $N spent (Phase 5)
- :class:`BudgetPercent` — at percentage milestones of a named budget (Phase 5)
- ``"manual"`` — agent-triggered via :func:`checkpoint`
- ``None`` — checkpointing disabled
"""


@dataclass
class Retention:
    """Controls when checkpoint data is deleted."""

    after_eval: Literal["delete", "retain"] = "delete"
    """``"delete"`` (default) removes the checkpoint directory after successful
    eval completion; ``"retain"`` keeps it for later inspection or replay."""


@dataclass
class CheckpointConfig:
    """Agent-side checkpoint configuration.

    Pass to a checkpointing-aware agent on its constructor:

        react(checkpoint=CheckpointConfig(policy=TimeInterval(every=timedelta(minutes=15))))

    See ``design/plans/checkpointing-working.md`` §2 for the full semantic model.
    """

    policy: CheckpointPolicy = None
    """Checkpoint trigger. See :data:`CheckpointPolicy`. ``None`` disables
    checkpointing entirely."""

    sandbox_paths: dict[str, list[str]] = field(default_factory=dict)
    """Per-sandbox-name list of absolute paths to capture inside the sandbox.
    Empty / omitted means host-only checkpointing (no sandbox repos)."""

    max_consecutive_failures: int | None = None
    """If set, the sample fails after N consecutive failed checkpoint attempts.
    ``None`` (default) = unlimited tolerance. ``0`` = any failure is fatal."""

    retention: Retention = field(default_factory=Retention)
    """Controls when checkpoint data is deleted."""
