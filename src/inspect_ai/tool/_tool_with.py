from copy import copy

from inspect_ai._util.registry import (
    registry_info,
    registry_params,
    set_registry_info,
    set_registry_params,
)

from ._tool import Tool
from ._tool_description import ToolDescription, set_tool_description
from ._tool_info import parse_tool_info


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
    # get the existing tool info
    tool_info = parse_tool_info(tool)

    # provide parameter overrides
    if parameters:
        signature_param_names = tool_info.parameters.properties.keys()
        for param_name in parameters.keys():
            if param_name not in signature_param_names:
                raise ValueError(
                    f"tool_with error: no parameter named '{param_name}' "
                    + f"(valid parameters are {', '.join(signature_param_names)})"
                )
            tool_info.parameters.properties[param_name].description = parameters[
                param_name
            ]

    # copy the tool and set the descriptions on the new copy
    tool_copy = copy(tool)
    set_registry_info(tool_copy, registry_info(tool))
    set_registry_params(tool_copy, registry_params(tool))
    set_tool_description(
        tool_copy,
        ToolDescription(
            name=name, description=description, parameters=tool_info.parameters
        ),
    )
    return tool_copy
