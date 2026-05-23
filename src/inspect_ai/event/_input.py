from typing import Any, Literal

from pydantic import BaseModel, Field

from inspect_ai.event._base import BaseEvent


class InputField(BaseModel):
    """One field of an `ask_user` request."""

    name: str
    """Property name in the request schema."""

    type: Literal["string", "integer", "number", "boolean", "array"]
    """JSON Schema type of the property."""

    description: str | None = Field(default=None)
    """Human-readable description of the field (from the request schema)."""


class InputEvent(BaseEvent):
    """Input screen interaction."""

    event: Literal["input"] = Field(default="input")
    """Event type."""

    input: str
    """Input interaction (plain text)."""

    input_ansi: str
    """Input interaction (ANSI)."""

    message: str | None = Field(default=None)
    """Prompt shown to the user (set for `ask_user`/`request_input` interactions)."""

    fields: list[InputField] | None = Field(default=None)
    """Fields requested from the user (set for `ask_user`/`request_input` interactions)."""

    outcome: Literal["accepted", "declined", "cancelled"] | None = Field(default=None)
    """How the `ask_user` interaction concluded."""

    content: dict[str, Any] | None = Field(default=None)
    """Structured answer when `outcome == "accepted"`."""
