from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class AnchorEvent(BaseEvent):
    """Marks a rollback-able point in a replayable trajectory.

    Emitted by an orchestrator immediately after a step it can later roll
    back to (a staged message, a model generate, etc.). Carries no content;
    ``anchor_id`` is the addressable identifier that ``TimelineSpan.branched_from``
    references. Hidden from the viewer transcript by default.
    """

    event: Literal["anchor"] = Field(default="anchor")
    """Event type."""

    anchor_id: str
    """Identifier for this anchor point. ``TimelineSpan.branched_from`` matches this."""

    source: str | None = Field(default=None)
    """Qualname of the recorded function that produced the anchored value (debugging aid)."""
