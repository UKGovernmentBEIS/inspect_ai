from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class BranchEvent(BaseEvent):
    """Branch in conversation history."""

    event: Literal["branch"] = Field(default="branch")
    """Event type."""

    from_span: str
    """Span where the branch originated."""

    from_message: str
    """Message at the branch point."""
