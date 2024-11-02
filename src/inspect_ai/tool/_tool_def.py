from copy import copy
from typing import (
    Any,
    Callable,
    NamedTuple,
)

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_info,
    set_registry_info,
    set_registry_params,
)

from ._tool import TOOL_PARALLEL, TOOL_PROMPT, TOOL_VIEWER, Tool
from ._tool_call import ToolCallViewer
from ._tool_description import (
    ToolDescription,
    set_tool_description,
    tool_description,
)
from ._tool_info import parse_tool_info
from ._tool_params import ToolParams


class ToolDef:
    def __init__(
        self,
        tool: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        parameters: dict[str, str] | ToolParams | None = None,
        parallel: bool | None = None,
        viewer: ToolCallViewer | None = None,
    ) -> None:
        """Tool definition.

        Args:
          tool (Callable[..., Any]): Callable to execute tool.
          name (str | None): Name of tool. Discovered automatically if not specified.
          description (str | None): Description of tool. Discovered automatically
            by parsing doc comments if not specified.
          parameters (dict[str,str] | ToolParams | None): Tool parameter descriptions and types.
             Discovered automatically by parsing doc comments if not specified.
          parallel (bool | None): Does the tool support parallel execution
             (defaults to True if not specified)
          viewer (ToolCallViewer | None): Optional tool call viewer implementation.

        Returns:
          Tool definition.
        """
        # tool
        self.tool = tool

        # if this is already a tool then initialise defaults from the tool
        if is_registry_object(tool) and registry_info(tool).type == "tool":
            tdef = tool_def_fields(tool)
            self.name = name or tdef.name
            self.description = description or tdef.description
            if isinstance(parameters, ToolParams):
                self.parameters = parameters
            else:
                self.parameters = tdef.parameters
                if parameters is not None:
                    apply_description_overrides(self.parameters, parameters)

            parameters = parameters if parameters is not None else tdef.parameters
            self.parallel = parallel if parallel is not None else tdef.parallel
            self.viewer = viewer or tdef.viewer

        # if its not a tool then extract tool_info if all fields have not
        # been provided explicitly
        else:
            if (
                name is None
                or description is None
                or parameters is None
                or not isinstance(parameters, ToolParams)
            ):
                tool_info = parse_tool_info(tool)
                self.name = name or tool_info.name
                self.description = description or tool_info.description
                if parameters:
                    if not isinstance(parameters, ToolParams):
                        self.parameters = copy(tool_info.parameters)
                        apply_description_overrides(self.parameters, parameters)
                    else:
                        self.parameters = parameters
                else:
                    self.parameters = tool_info.parameters
            else:
                self.name = name
                self.description = description
                self.parameters = parameters

            # behavioral attributes
            self.parallel = parallel is not False
            self.viewer = viewer

    tool: Callable[..., Any]
    """Callable to execute tool."""

    name: str
    """Tool name."""

    description: str
    """Tool description."""

    parameters: ToolParams
    """Tool parameter descriptions."""

    parallel: bool
    """Supports parallel execution."""

    viewer: ToolCallViewer | None
    """Custom viewer for tool call"""

    def as_tool(self) -> Tool:
        """Convert a ToolDef to a Tool."""
        tool = self.tool
        info = RegistryInfo(
            type="tool",
            name=self.name,
            metadata={TOOL_PARALLEL: self.parallel, TOOL_VIEWER: self.viewer},
        )
        set_registry_info(tool, info)
        set_registry_params(tool, {})
        set_tool_description(
            tool,
            ToolDescription(
                name=self.name,
                description=self.description,
                parameters=self.parameters,
            ),
        )
        return tool


# helper function to apply description overrides
def apply_description_overrides(target: ToolParams, overrides: dict[str, str]) -> None:
    for param, value in overrides.items():
        if param not in target.properties.keys():
            raise ValueError(
                f"'{param}' is not a valid parameter for the target function."
            )
        target.properties[param].description = value


def tool_defs(
    tools: list[Tool] | list[ToolDef] | list[Tool | ToolDef],
) -> list[ToolDef]:
    return [ToolDef(tool) if isinstance(tool, Tool) else tool for tool in tools]


class ToolDefFields(NamedTuple):
    name: str
    description: str
    parameters: ToolParams
    parallel: bool
    viewer: ToolCallViewer | None


def tool_def_fields(tool: Tool) -> ToolDefFields:
    # get tool_info
    name, prompt, parallel, viewer = tool_registry_info(tool)
    tool_info = parse_tool_info(tool)

    # if there is a description then append any prompt to the
    # the description (note that 'prompt' has been depreacted
    # in favor of just providing a description in the doc comment.
    if tool_info.description:
        if prompt:
            tool_info.description = f"{tool_info.description}. {prompt}"

    # if there is no description and there is a prompt, then use
    # the prompt as the description
    elif prompt:
        tool_info.description = prompt

    # no description! we can't proceed without one
    else:
        raise ValueError(f"Description not provided for tool function '{name}'")

    # validate that we have types/descriptions for paramters
    for param_name, param in tool_info.parameters.properties.items():

        def raise_not_provided_error(context: str) -> None:
            raise ValueError(
                f"{context} not provided for parameter '{param_name}' of tool function '{name}'."
            )

        if param.type == "null":
            raise_not_provided_error("Type annotation")
        elif not param.description:
            raise_not_provided_error("Description")

    # see if the user has overriden any of the tool's descriptions
    desc = tool_description(tool)
    if desc.name:
        name = desc.name
    if desc.description:
        tool_info.description = desc.description
    if desc.parameters:
        for key, param in desc.parameters.properties.items():
            if key in tool_info.parameters.properties.keys():
                tool_info.parameters.properties[key].description = param.description

    # build tool def
    return ToolDefFields(
        name=name,
        description=tool_info.description,
        parameters=tool_info.parameters,
        parallel=parallel,
        viewer=viewer,
    )


def tool_registry_info(
    tool: Tool,
) -> tuple[str, str | None, bool, ToolCallViewer | None]:
    info = registry_info(tool)
    name = info.name.split("/")[-1]
    prompt = info.metadata.get(TOOL_PROMPT, None)
    parallel = info.metadata.get(TOOL_PARALLEL, True)
    viewer = info.metadata.get(TOOL_VIEWER, None)
    return name, prompt, parallel, viewer
