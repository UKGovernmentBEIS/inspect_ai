"""Checkpoint trigger strategies.

Each concrete trigger lives in its own module. The
:class:`CheckpointTrigger` protocol is in :mod:`._base`.
"""

from ._base import CheckpointTrigger
from ._manual import Manual
from ._time_interval import TimeInterval
from ._turn_interval import TurnInterval

__all__ = [
    "CheckpointTrigger",
    "Manual",
    "TimeInterval",
    "TurnInterval",
]
