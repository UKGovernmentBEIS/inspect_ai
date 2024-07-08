from dataclasses import dataclass, field
from typing import Any

from inspect_ai._util.json import JSONType


@dataclass
class ToolParam:
    name: str
    """Parameter name."""

    type: JSONType
    """JSON type of parameter."""

    description: str
    """Description of parameter."""

    optional: bool
    """Is the parameter optional"""

    properties: dict[str, Any] = field(default_factory=dict)
    """Additional properties for tool param.

    For example: properties={"items": {"type": "string"}} for a list of strings as tool param."""


@dataclass
class ToolInfo:
    name: str
    """Tool name."""

    description: str
    """Tool description."""

    params: list[ToolParam]
    """Tool parameters"""
