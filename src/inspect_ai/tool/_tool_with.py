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
    """Tool with modifications to various attributes.

    This function modifies the passed tool in place and
    returns it. If you want to create multiple variations
    of a single tool using `tool_with()` you should create
    the underlying tool multiple times.

    Args:
       tool: Tool instance to modify.
       name: Tool name (optional).
       description: Tool description (optional).
       parameters: Parameter descriptions (optional)
       parallel: Does the tool support parallel execution
          (defaults to True if not specified)
       viewer: Optional tool call viewer implementation.
       model_input: Optional function that determines how
           tool call results are played back as model input.

    Returns:
       The passed tool with the requested modifications.
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

    # resolve attributes
    info = registry_info(tool).model_copy()
    if parallel is not None:
        info.metadata[TOOL_PARALLEL] = parallel
    elif viewer is not None:
        info.metadata[TOOL_VIEWER] = viewer
    elif model_input is not None:
        info.metadata[TOOL_MODEL_INPUT] = model_input

    # set attributes
    set_registry_info(tool, info)
    set_registry_params(tool, registry_params(tool))
    set_tool_description(
        tool,
        ToolDescription(
            name=name, description=description, parameters=tool_info.parameters
        ),
    )
    return tool
