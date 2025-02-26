from typing import (
    Any,
    Literal,
    Optional,
)

from pydantic import BaseModel, Field

JSONType = Literal["string", "integer", "number", "boolean", "array", "object", "null"]
"""Validate types within JSON schema."""


class ToolParam(BaseModel):
    """Description of tool parameter in JSON Schema format."""

    type: JSONType | None = Field(default=None)
    """JSON type of tool parameter."""

    description: str | None = Field(default=None)
    """Parameter description."""

    default: Any = Field(default=None)
    """Default value for parameter."""

    enum: list[Any] | None = Field(default=None)
    """Valid values for enum parameters."""

    items: Optional["ToolParam"] = Field(default=None)
    """Valid type for array parameters."""

    properties: dict[str, "ToolParam"] | None = Field(default=None)
    """Valid fields for object parametrs."""

    additionalProperties: Optional["ToolParam"] | bool | None = Field(default=None)
    """Are additional properties allowed?"""

    anyOf: list["ToolParam"] | None = Field(default=None)
    """Valid types for union parameters."""

    required: list[str] | None = Field(default=None)
    """Required fields for object parameters."""


class ToolParams(BaseModel):
    """Description of tool parameters object in JSON Schema format."""

    type: Literal["object"] = Field(default="object")
    """Params type (always 'object')"""

    properties: dict[str, ToolParam] = Field(default_factory=dict)
    """Tool function parameters."""

    required: list[str] = Field(default_factory=list)
    """List of required fields."""

    additionalProperties: bool = Field(default=False)
    """Are additional object properties allowed? (always `False`)"""
