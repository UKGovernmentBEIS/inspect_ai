from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Literal,
    Union,
)

from inspect_ai._util.error import exception_message
from inspect_ai._util.json import JSONType
from inspect_ai._util.registry import registry_info


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
class ToolDef:
    name: str
    """Tool name."""

    description: str
    """Tool description."""

    prompt: str | None
    """System prommpt text to guide model usage of tool."""

    params: list[ToolParam]
    """Tool parameters"""

    tool: Callable[..., Any]
    """Callable to execute tool."""


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


async def call_tool(
    tools: list[ToolDef], call: ToolCall, metadata: dict[str, Any]
) -> Any:
    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        return f"Tool {call.function} not found"

    # resolve metadata params and prepend to arguments
    tool_params: dict[str, str] = registry_info(tool_def.tool).metadata.get(
        TOOL_PARAMS, {}
    )
    resolved_params: dict[str, Any] = {}
    for name, value in tool_params.items():
        key = value.removeprefix("metadata.")
        resolved = metadata.get(key, None)
        if resolved is None:
            raise ValueError(f"Metadata value '{key}' not found for tool parameter")
        resolved_params[name] = resolved
    arguments = resolved_params | call.arguments

    # call the tool
    try:
        return await tool_def.tool(**arguments)
    except Exception as e:
        return f"Error: {exception_message(e)}"


TOOL_PROMPT = "prompt"
TOOL_PARAMS = "params"
