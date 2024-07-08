from dataclasses import dataclass

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


@dataclass
class ToolInfo:
    name: str
    """Tool name."""

    description: str
    """Tool description."""

    params: list[ToolParam]
    """Tool parameters"""
