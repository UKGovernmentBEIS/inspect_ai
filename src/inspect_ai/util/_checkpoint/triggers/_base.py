"""Checkpoint trigger strategy protocol.

A ``CheckpointTrigger`` decides — at each agent turn boundary — whether
a checkpoint should fire. The :class:`Checkpointer` holds one instance
per sample session and delegates ``tick()`` to it; the trigger keeps
whatever state it needs (turn counts, time of last fire, etc.) locally.

Each concrete trigger lives in its own module under this package.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

CheckpointTriggerKind = Literal["time", "turn", "manual"]
"""Identifier of which trigger fired, as recorded on the sidecar.

Distinct from :class:`CheckpointTrigger`, which is the strategy
protocol implemented by each trigger. This is the runtime *label*
recorded on the sidecar for the trigger that fired this checkpoint.
"""


class CheckpointTrigger(Protocol):
    """Strategy for deciding when a checkpoint should fire.

    The :class:`Checkpointer` calls ``tick()`` once per agent turn
    boundary. Return the :data:`CheckpointTriggerKind` label this
    trigger fires under (written into the sidecar) when a checkpoint
    should fire at this boundary, or ``None`` to skip. The trigger
    owns its own state — the same instance is reused across ``tick()``
    calls for the lifetime of one sample.
    """

    def tick(self) -> CheckpointTriggerKind | None: ...


# Pydantic walks `dataset.Sample` (a BaseModel) into `CheckpointSampleConfig`
# (a @dataclass) into its `trigger: CheckpointTrigger | None` field.
# A Protocol has no schema pydantic can build — concrete trigger instances
# are runtime-only strategy objects with no JSON contract. Attach a hook
# that tells pydantic to accept any object for this type. `setattr` is
# used to avoid grafting `__get_pydantic_core_schema__` onto the Protocol's
# interface (concrete triggers shouldn't have to implement it).
def _trigger_pydantic_schema(
    cls: type, source_type: Any, handler: GetCoreSchemaHandler
) -> CoreSchema:
    return core_schema.any_schema()


setattr(
    CheckpointTrigger,
    "__get_pydantic_core_schema__",
    classmethod(_trigger_pydantic_schema),
)
