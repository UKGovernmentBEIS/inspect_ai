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
    NonManualCheckpointPolicy,
    Retention,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from ._layout import CheckpointManifest, CheckpointSidecar, CheckpointTrigger

__all__ = [
    "BudgetPercent",
    "CheckpointConfig",
    "CheckpointManifest",
    "CheckpointPolicy",
    "CheckpointSidecar",
    "CheckpointTrigger",
    "Checkpointer",
    "CostInterval",
    "NonManualCheckpointPolicy",
    "Retention",
    "TimeInterval",
    "TokenInterval",
    "TurnInterval",
    "checkpoint",
]
