from copy import deepcopy

from inspect_ai._util.registry import (
    registry_info,
    registry_params,
    set_registry_info,
    set_registry_params,
)
from inspect_ai.tool._tool_call import ToolCallModelInput, ToolCallViewer

from ._tool import TOOL_MODEL_INPUT, TOOL_PARALLEL, TOOL_VIEWER, Tool
from ._tool_description import ToolDescription, set_tool_description
from ._tool_info import parse_tool_info


def tool_with(
    tool: Tool,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, str] | None = None,
    parallel: bool | None = None,
    viewer: ToolCallViewer | None = None,
    model_input: ToolCallModelInput | None = None,
) -> Tool:
    """Tool with modifications to name and descriptions.

    Args:
       tool (Tool): Tool instance to copy and add descriptions to.
       name (str | None): Tool name (optional).
       description (str | None): Tool description (optional).
       parameters (dict[str,str] | None): Parameter descriptions (optional)
       parallel (bool | None): Does the tool support parallel execution
          (defaults to True if not specified)
       viewer (ToolCallViewer | None): Optional tool call viewer implementation.
       model_input (ToolCallModelInput | None): Optional function that determines how
           tool call results are played back as model input.

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
    tool_copy = deepcopy(tool)
    info = registry_info(tool).model_copy()
    if parallel is not None:
        info.metadata[TOOL_PARALLEL] = parallel
    elif viewer is not None:
        info.metadata[TOOL_VIEWER] = viewer
    elif model_input is not None:
        info.metadata[TOOL_MODEL_INPUT] = model_input

    set_registry_info(tool_copy, info)
    set_registry_params(tool_copy, registry_params(tool))
    set_tool_description(
        tool_copy,
        ToolDescription(
            name=name, description=description, parameters=tool_info.parameters
        ),
    )
    return tool_copy
