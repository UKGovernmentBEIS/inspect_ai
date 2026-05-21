from typing import Literal

from pydantic import ConfigDict, Field

from inspect_ai.event._base import BaseEvent
from inspect_ai.util._checkpoint._layout.sidecar import CheckpointDetails


class CheckpointEvent(BaseEvent, CheckpointDetails):
    """A successful checkpoint commit.

    Emitted by the checkpointer immediately after the per-checkpoint
    sidecar JSON is written — see working.md §8a. Carries the full
    sidecar payload flattened into top-level fields (via multiple
    inheritance from :class:`CheckpointDetails`), so a consumer of
    ``transcript().events`` (or the ``.eval`` log) reads
    ``event.checkpoint_id`` / ``event.trigger`` / ``event.host`` etc.
    directly — same data as someone reading
    ``<sample>/ckpt-NNNNN.json`` from disk.
    """

    # `extra="allow"` inherited from CheckpointDetails; re-declared for
    # clarity and forward-compat with future sidecar additions.
    model_config = ConfigDict(extra="allow")

    event: Literal["checkpoint"] = Field(default="checkpoint")
    """Event type."""

    @classmethod
    def from_details(cls, details: CheckpointDetails) -> "CheckpointEvent":
        """Construct an event from an already-built sidecar.

        Used at fire time (one sidecar built in ``_fire`` → written to
        disk + emitted as event) and at resume time (sidecar read from
        ``ckpt-NNNNN.json`` → reconstructed event for the trailing
        commit that didn't make it into its own ``events.json``).
        """
        return cls(**details.model_dump())
