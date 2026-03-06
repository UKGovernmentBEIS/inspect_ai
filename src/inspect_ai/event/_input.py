from typing import Literal

from pydantic import Field

from inspect_ai.event._base import BaseEvent


class InputEvent(BaseEvent):
    """Input screen interaction."""

    event: Literal["input"] = Field(default="input")
    """Event type."""

    input: str
    """Input interaction (plain text)."""

    input_ansi: str
    """Input interaction (ANSI)."""
