"""Inspect checkpointing — agent-side policy primitives.

Public surface for agent authors integrating checkpointing into their
loop. See ``design/plans/checkpointing-working.md`` §2 for the full
semantic model.

Phase 2 ships the policy types, :class:`Checkpointer`, and the manual
:func:`checkpoint` trigger. Firing is a no-op; Phase 3 replaces it with
real writes.
"""

from ._checkpointer import Checkpointer, checkpoint
from ._config import (
    BudgetPercent,
    CheckpointConfig,
    CheckpointPolicy,
    CostInterval,
    Retention,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)

__all__ = [
    "BudgetPercent",
    "CheckpointConfig",
    "CheckpointPolicy",
    "Checkpointer",
    "CostInterval",
    "Retention",
    "TimeInterval",
    "TokenInterval",
    "TurnInterval",
    "checkpoint",
]
