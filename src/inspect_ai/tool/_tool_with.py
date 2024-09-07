import inspect
from copy import copy
from dataclasses import dataclass

from inspect_ai._util.registry import (
    registry_info,
    registry_params,
    set_registry_info,
    set_registry_params,
)

from ._tool import Tool


def tool_with(
    tool: Tool,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, str] | None = None,
) -> Tool:
    """Tool with modifications to name and descriptions.

    Args:
       tool (Tool): Tool instance to copy and add descriptions to.
       name (str | None): Tool name (optional).
       description (str | None): Tool description (optional).
       parameters (dict[str,str] | None): Parameter descriptions (optional)

    Returns:
       A copy of the passed tool with the specified descriptive information.
    """
    # validate that the parameters are all part of the tool's signature
    if parameters:
        signature_param_names = inspect.signature(tool).parameters.keys()
        for param_name in parameters.keys():
            if param_name not in signature_param_names:
                raise ValueError(
                    f"tool_with error: no parameter named '{param_name}' "
                    + f"(valid parameters are {', '.join(signature_param_names)})"
                )

    # copy the tool and set the descriptions on the new copy
    tool_copy = copy(tool)
    set_registry_info(tool_copy, registry_info(tool))
    set_registry_params(tool_copy, registry_params(tool))
    set_tool_description(
        tool_copy,
        ToolDescription(name=name, description=description, parameters=parameters),
    )
    return tool_copy


@dataclass
class ToolDescription:
    name: str | None = None
    description: str | None = None
    parameters: dict[str, str] | None = None


def tool_description(tool: Tool) -> ToolDescription:
    return getattr(tool, TOOL_DESCRIPTION, ToolDescription())


def set_tool_description(tool: Tool, description: ToolDescription) -> None:
    setattr(tool, TOOL_DESCRIPTION, description)


TOOL_DESCRIPTION = "__TOOL_DESCRIPTION__"
