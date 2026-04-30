"""Inspect checkpointing — agent-side primitives.

Public surface for agent authors integrating checkpointing into their
loop. See ``design/plans/checkpointing-working.md`` §2 for the full
semantic model.
"""

from ._checkpointer import Checkpointer
from ._config import (
    BudgetPercent,
    CheckpointConfig,
    CheckpointTrigger,
    CostInterval,
    NonManualCheckpointTrigger,
    Retention,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from ._layout import (
    CheckpointManifest,
    CheckpointSidecar,
    CheckpointTriggerKind,
    SnapshotInfo,
)

__all__ = [
    "BudgetPercent",
    "CheckpointConfig",
    "CheckpointManifest",
    "CheckpointSidecar",
    "CheckpointTrigger",
    "CheckpointTriggerKind",
    "Checkpointer",
    "CostInterval",
    "NonManualCheckpointTrigger",
    "Retention",
    "SnapshotInfo",
    "TimeInterval",
    "TokenInterval",
    "TurnInterval",
]
