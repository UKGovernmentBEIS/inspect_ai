"""Inspect checkpointing — agent-side primitives.

Public surface re-exported via :mod:`inspect_ai.util`. Other modules
in the package (``layout``, ``parse_cli``, ``hydrate``,
``_sandbox_restic``, …) are import-from-leaf-module only when external
callers genuinely need them. See
``design/plans/checkpointing-working.md`` §2 for the full semantic
model.
"""

from ._triggers import (
    CheckpointTrigger,
    Manual,
    TimeInterval,
    TokenInterval,
    TurnInterval,
)
from .checkpointer import Attempt, Checkpointer, checkpointer
from .config import (
    CheckpointConfig,
    CheckpointSampleConfig,
    normalize_checkpoint,
)

__all__ = [
    "Attempt",
    "CheckpointConfig",
    "CheckpointSampleConfig",
    "CheckpointTrigger",
    "Manual",
    "TimeInterval",
    "TokenInterval",
    "TurnInterval",
    "checkpointer",
    "Checkpointer",
    "normalize_checkpoint",
]
