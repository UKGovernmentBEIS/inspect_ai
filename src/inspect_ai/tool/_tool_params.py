from typing import (
    Literal,
    TypeAlias,
)

from pydantic import BaseModel, Field

from inspect_ai.util._json import JSONSchema

ToolParam: TypeAlias = JSONSchema
"""Description of tool parameter in JSON Schema format."""


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
