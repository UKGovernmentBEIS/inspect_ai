"""Checkpoint trigger strategy protocol.

A ``CheckpointTrigger`` decides — at each agent turn boundary — whether
a checkpoint should fire. The :class:`Checkpointer` holds one instance
per sample session and delegates ``tick()`` to it; the trigger keeps
whatever state it needs (turn counts, time of last fire, etc.) locally.

Each concrete trigger lives in its own module under this package.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from inspect_ai.util._checkpoint.layout import CheckpointTriggerKind


class CheckpointTrigger(Protocol):
    """Strategy for deciding when a checkpoint should fire.

    Each concrete trigger declares a class-level :attr:`kind` label
    (recorded on the sidecar when this trigger fires) and implements
    ``tick()``. The :class:`Checkpointer` calls ``tick()`` once per
    agent turn boundary and consults ``kind`` if it returns ``True``.
    The trigger owns its own state — the same instance is reused
    across ``tick()`` calls for the lifetime of one sample.
    """

    kind: ClassVar[CheckpointTriggerKind]

    def tick(self) -> bool: ...


def _trigger_pydantic_schema(
    cls: type, source_type: Any, handler: GetCoreSchemaHandler
) -> CoreSchema:
    # Triggers are runtime-only strategy instances; pydantic can't walk
    # the Protocol to build a schema, so accept any object here. Used
    # when a pydantic model (e.g. ``dataset.Sample``) contains a
    # :class:`CheckpointSampleConfig` field whose ``trigger`` is typed
    # ``CheckpointTrigger``.
    return core_schema.any_schema()


# Register pydantic's schema hook on the Protocol class itself, after
# class definition, so it's *not* part of the Protocol's interface
# (concrete trigger classes don't need to implement it).
CheckpointTrigger.__get_pydantic_core_schema__ = classmethod(  # type: ignore[attr-defined]
    _trigger_pydantic_schema
)
