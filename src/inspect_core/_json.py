from typing import (
    Any,
    Literal,
    Optional,
)

from pydantic import BaseModel, Field

JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
"""Valid types within JSON schema."""


class JSONSchema(BaseModel):
    """JSON Schema for type."""

    type: JSONType | list[JSONType] | None = Field(default=None)
    """JSON type of tool parameter."""

    format: str | None = Field(default=None)
    """Format of the parameter (e.g. date-time)."""

    description: str | None = Field(default=None)
    """Parameter description."""

    default: Any = Field(default=None)
    """Default value for parameter."""

    enum: list[Any] | None = Field(default=None)
    """Valid values for enum parameters."""

    items: Optional["JSONSchema"] = Field(default=None)
    """Valid type for array parameters."""

    properties: dict[str, "JSONSchema"] | None = Field(default=None)
    """Valid fields for object parametrs."""

    additionalProperties: Optional["JSONSchema"] | bool | None = Field(default=None)
    """Are additional properties allowed?"""

    anyOf: list["JSONSchema"] | None = Field(default=None)
    """Valid types for union parameters."""

    required: list[str] | None = Field(default=None)
    """Required fields for object parameters."""

    pattern: str | None = Field(default=None)
    """Regex pattern for string parameters."""

    minLength: int | None = Field(default=None)
    """Minimum length for string parameters."""

    maxLength: int | None = Field(default=None)
    """Maximum length for string parameters."""

    minimum: int | float | None = Field(default=None)
    """Minimum value for numeric parameters."""

    maximum: int | float | None = Field(default=None)
    """Maximum value for numeric parameters."""

    examples: list[Any] | None = Field(default=None)
    """Example values for the parameter."""
