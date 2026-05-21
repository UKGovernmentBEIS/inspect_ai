"""Trigger protocol + factory.

A :class:`Trigger` is the per-session runtime object that owns
whatever state the trigger needs (turn counter, last-fire monotonic,
…). :func:`create_trigger` dispatches on the spec's concrete type
and returns the matching implementation from this subpackage. The
concrete classes are private to this subpackage; callers depend only
on the protocol.
"""

from __future__ import annotations

from .manual import _ManualTrigger
from .time import _TimeIntervalTrigger
from .token import _TokenIntervalTrigger
from .turn import _TurnIntervalTrigger
from .types import (
    CheckpointTrigger,
    Manual,
    TimeInterval,
    TokenInterval,
    Trigger,
    TurnInterval,
)


def create_trigger(spec: CheckpointTrigger) -> Trigger:
    """Construct the concrete :class:`Trigger` for ``spec``."""
    match spec:
        case Manual():
            return _ManualTrigger()
        case TurnInterval(every=n):
            return _TurnIntervalTrigger(n)
        case TimeInterval(every=t):
            return _TimeIntervalTrigger(t)
        case TokenInterval(every=n):
            return _TokenIntervalTrigger(n)
        case _:
            raise NotImplementedError(
                f"No runtime trigger yet for spec {type(spec).__name__}"
            )
