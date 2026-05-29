from typing import Literal

from pydantic import ConfigDict, Field

from inspect_ai.event._base import BaseEvent
from inspect_ai.util._checkpoint._layout.schemas import Checkpoint


class CheckpointEvent(BaseEvent, Checkpoint):
    """A successful checkpoint commit.

    Emitted by the checkpointer immediately after the per-checkpoint
    file JSON is written — see working.md §8a. Carries the full
    checkpoint payload flattened into top-level fields (via multiple
    inheritance from :class:`Checkpoint`), so a consumer of
    ``transcript().events`` (or the ``.eval`` log) reads
    ``event.checkpoint_id`` / ``event.trigger`` / ``event.host`` etc.
    directly — same data as someone reading
    ``<sample>/ckpt-NNNNN.json`` from disk.
    """

    # `extra="allow"` inherited from Checkpoint; re-declared for
    # clarity and forward-compat with future checkpoint file additions.
    model_config = ConfigDict(extra="allow")

    event: Literal["checkpoint"] = Field(default="checkpoint")
    """Event type."""

    @classmethod
    def from_details(cls, details: Checkpoint) -> "CheckpointEvent":
        """Construct an event from an already-built checkpoint.

        Used at fire time (one checkpoint built in ``_fire`` → written
        to disk + emitted as event) and at resume time (checkpoint read
        from ``ckpt-NNNNN.json`` → reconstructed event for the trailing
        commit that didn't make it into its own ``events.json``).
        """
        return cls(**details.model_dump())
