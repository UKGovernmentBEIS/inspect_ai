"""Checkpoint trigger configuration types.

User-facing trigger specs — frozen dataclasses, pure data with no
runtime state. The per-session mutable state (turn counters,
time-of-last-fire, etc.) lives on the concrete :class:`Trigger`
implementations (see :mod:`.engine`), one instance of which is built
per sample-checkpointed session from the user's spec via
:func:`create_trigger`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol


@dataclass(frozen=True)
class Manual:
    """No-op trigger spec.

    The engine's ``tick()`` always returns ``None`` for this spec —
    fires happen only through explicit ``cp.checkpoint()`` calls.
    """


@dataclass(frozen=True)
class TurnInterval:
    """Fire after every ``every`` agent turns of work.

    The very first ``tick()`` call marks the boundary *before* turn 1
    has run — agents place ``cp.tick()`` at the top of their loop, so
    the opening tick stands between "no turn yet" and "turn 1." That
    boundary is informational and doesn't count toward the threshold;
    otherwise ``every=1`` would fire an empty checkpoint on the
    opening tick.
    """

    every: int


@dataclass(frozen=True)
class TimeInterval:
    """Fire after a wall-clock interval.

    The engine fires when at least ``every`` has elapsed since the
    last fire (or since the session opened, for the first fire).
    """

    every: timedelta


@dataclass(frozen=True)
class TokenInterval:
    """Fire every ``every`` tokens of sample-level usage.

    Sample total tokens are read from
    :func:`inspect_ai.model.sample_total_tokens`; the trigger fires
    each time the running total crosses another ``every``-token
    boundary since the last fire.
    """

    every: int


@dataclass(frozen=True)
class CostInterval:
    """Fire every ``every`` dollars of sample-level cost.

    Sample total cost is read from
    :func:`inspect_ai.model.sample_total_cost`; the trigger fires
    each time the running total crosses another ``every``-dollar
    boundary since the last fire.
    """

    every: float


BudgetKind = Literal["token", "cost", "time", "working"]
"""Which of the sample's tracked budgets ``BudgetPercent`` watches."""


@dataclass(frozen=True)
class BudgetPercent:
    """Fire on each ``percent``-percent slice of the active ``budget``.

    ``percent`` is in 0..100. With ``percent=25``, the trigger fires
    at ~25% / 50% / 75% / 100% of the relevant limit's usage. Has no
    effect when no limit is set for the chosen budget.
    """

    budget: BudgetKind
    percent: float


CheckpointTriggerKind = Literal["time", "turn", "manual", "token", "cost", "budget"]
"""Identifier of which trigger fired, as recorded on the checkpoint file."""

CheckpointTrigger = (
    Manual | TurnInterval | TimeInterval | TokenInterval | CostInterval | BudgetPercent
)
"""User-facing checkpoint trigger spec — a union of frozen dataclass
config types. See :mod:`._engine` for the runtime dispatch."""


class Trigger(Protocol):
    """Runtime trigger — one instance per checkpointed session."""

    def tick(self) -> CheckpointTriggerKind | None:
        """Advance the trigger's state; return the kind that fired, or ``None``."""
        ...
