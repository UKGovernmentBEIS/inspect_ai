from dataclasses import dataclass
from typing import (
    Any,
    Literal,
    Union,
)

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


@dataclass
class ToolCall:
    id: str
    """Unique identifer for tool call."""

    function: str
    """Function called."""

    arguments: dict[str, Any]
    """Arguments to function."""

    type: Literal["function"]
    """Type of tool call (currently only 'function')"""


@dataclass
class ToolFunction:
    name: str
    """The name of the function to call."""


ToolChoice = Union[Literal["none", "auto"], ToolFunction]
"""Specify which tool to call.

"auto" means the model decides; "none" means never call a tool; and
ToolFunction instructs the model to call a specific function.
"""
