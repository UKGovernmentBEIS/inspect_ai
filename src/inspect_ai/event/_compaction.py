from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class CompactionEvent(BaseEvent):
    """Compaction of conversation history."""

    event: Literal["compaction"] = Field(default="compaction")
    """Event type."""

    type: Literal["summary", "edit", "trim"] = Field(default="summary")
    """Compaction type."""

    tokens_before: int | None = Field(default=None)
    """Tokens before compaction."""

    tokens_after: int | None = Field(default=None)
    """Tokens after compaction."""

    source: str | None = Field(default=None)
    """Compaction source (e.g. 'inspect', 'claude_code', etc.)"""
