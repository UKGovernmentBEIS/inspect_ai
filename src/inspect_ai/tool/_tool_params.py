from typing import (
    Any,
    Literal,
    Optional,
    TypeAlias,
)

from pydantic import BaseModel, Field, model_validator

from inspect_ai.util._json import JSONSchema

ToolParam: TypeAlias = JSONSchema
"""Description of tool parameter in JSON Schema format."""


class ToolParams(BaseModel):
    """Description of tool parameters object in JSON Schema format."""

    type: Literal["object"] = Field(default="object")
    """Params type (always 'object')"""

    @model_validator(mode="before")
    @classmethod
    def _normalize_types(cls, data: Any) -> Any:
        if isinstance(data, dict) and "type" in data:
            v = data["type"]
            if isinstance(v, str):
                data = {**data, "type": v.lower()}
        return data

    properties: dict[str, ToolParam] = Field(default_factory=dict)
    """Tool function parameters."""

    required: list[str] = Field(default_factory=list)
    """List of required fields."""

    additionalProperties: Optional[JSONSchema] | bool = Field(default=False)
    """Are additional object properties allowed?"""
