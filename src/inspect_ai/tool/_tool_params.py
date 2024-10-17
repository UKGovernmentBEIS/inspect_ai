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

    type: JSONType = Field(default="null")
    description: str | None = Field(default=None)
    default: Any = Field(default=None)
    items: Optional["ToolParam"] = Field(default=None)
    properties: dict[str, "ToolParam"] | None = Field(default=None)
    additionalProperties: Optional["ToolParam"] | bool | None = Field(default=None)
    anyOf: list["ToolParam"] | None = Field(default=None)
    required: list[str] | None = Field(default=None)


class ToolParams(BaseModel):
    """Description of tool parameters object in JSON Schema format."""

    type: Literal["object"] = Field(default="object")
    properties: dict[str, ToolParam] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additionalProperties: bool = Field(default=False)
