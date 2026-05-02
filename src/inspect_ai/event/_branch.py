from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class BranchEvent(BaseEvent):
    """Marks where a branched trajectory's unique content begins.

    Emitted at the point where a branch transitions from replaying its
    parent's prefix to live execution. Events before this in the trajectory's
    span are replay-phase re-execution; events after are the branch's
    genuine new content.
    """

    event: Literal["branch"] = Field(default="branch")
    """Event type."""

    from_span: str
    """Span where the branch originated (parent trajectory's span_id)."""

    from_anchor: str
    """Anchor at the branch point (matches an ``AnchorEvent.anchor_id`` in the parent)."""
