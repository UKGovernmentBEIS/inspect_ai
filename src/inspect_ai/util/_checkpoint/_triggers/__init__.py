"""Checkpoint trigger configs + runtime factory.

User-facing spec dataclasses live in :mod:`.config` (frozen, pure
data). :mod:`.engine` exposes the :class:`Trigger` protocol and
:func:`create_trigger` factory; the concrete trigger classes live in
sibling private modules and are not re-exported.
"""

from .factory import create_trigger
from .types import (
    CheckpointTrigger,
    CheckpointTriggerKind,
    Manual,
    TimeInterval,
    TokenInterval,
    Trigger,
    TriggerFire,
    TurnInterval,
)

__all__ = [
    "CheckpointTrigger",
    "CheckpointTriggerKind",
    "Manual",
    "TimeInterval",
    "TokenInterval",
    "Trigger",
    "TriggerFire",
    "TurnInterval",
    "create_trigger",
]
