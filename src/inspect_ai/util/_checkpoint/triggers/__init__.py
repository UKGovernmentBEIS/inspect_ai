"""Checkpoint trigger strategies.

Each concrete trigger lives in its own module. The
:class:`CheckpointTrigger` protocol is in :mod:`._base`.
"""

from ._base import CheckpointTrigger, CheckpointTriggerKind
from ._manual import Manual
from ._time_interval import TimeInterval
from ._turn_interval import TurnInterval

__all__ = [
    "CheckpointTrigger",
    "CheckpointTriggerKind",
    "Manual",
    "TimeInterval",
    "TurnInterval",
]
