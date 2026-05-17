"""Inspect checkpointing — agent-side primitives.

Public surface re-exported via :mod:`inspect_ai.util`. The names below
are the *only* symbols this package exposes to external callers; the
broader set of layout types, parsers, and ContextVar accessors are
import-from-leaf-module only (see ``layout.py``, ``parse.py``,
``session.py``). See ``design/plans/checkpointing-working.md`` §2
for the full semantic model.
"""

from .checkpointer import checkpointer
from .config import (
    CheckpointConfig,
    CheckpointSampleConfig,
    Retention,
)
from .triggers import (
    CheckpointTrigger,
    Manual,
    TimeInterval,
    TurnInterval,
)

__all__ = [
    "CheckpointConfig",
    "CheckpointSampleConfig",
    "CheckpointTrigger",
    "Manual",
    "Retention",
    "TimeInterval",
    "TurnInterval",
    "checkpointer",
]
