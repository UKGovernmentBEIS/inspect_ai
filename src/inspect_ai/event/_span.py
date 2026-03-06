from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class SpanBeginEvent(BaseEvent):
    """Mark the beginning of a transcript span."""

    event: Literal["span_begin"] = Field(default="span_begin")
    """Event type."""

    id: str
    """Unique identifier for span."""

    parent_id: str | None = Field(default=None)
    """Identifier for parent span."""

    type: str | None = Field(default=None)
    """Optional 'type' field for span."""

    name: str
    """Span name."""


class SpanEndEvent(BaseEvent):
    """Mark the end of a transcript span."""

    event: Literal["span_end"] = Field(default="span_end")
    """Event type."""

    id: str
    """Unique identifier for span."""
