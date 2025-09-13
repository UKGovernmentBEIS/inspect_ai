from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue


class Reference(BaseModel):
    """Reference to scanned content."""

    type: Literal["message", "event"]
    """Reference type."""

    id: str
    """Reference id (message or event id)"""


class Result(BaseModel):
    """Scanner result."""

    value: JsonValue
    """Scanner value."""

    answer: str | None = Field(default=None)
    """Answer extracted from model output (optional)"""

    explanation: str | None = Field(default=None)
    """Explanation of result (optional)."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional metadata related to the result"""

    references: list[Reference] = Field(default_factory=list)
    """References to relevant messages or events."""
