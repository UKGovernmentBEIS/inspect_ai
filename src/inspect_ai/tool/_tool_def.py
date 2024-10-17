from copy import copy
from typing import (
    Any,
    Callable,
)

from inspect_ai._util.registry import (
    RegistryInfo,
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
        parallel: bool = True,
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
          parallel (bool): Does the tool support parallel execution (defaults to True)
          viewer (ToolCallViewer | None): Optional tool call viewer implementation.

        Returns:
          Tool definition.
        """
        # tool
        self.tool = tool

        # tool info
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
                    for param, value in parameters.items():
                        if param not in self.parameters.properties.keys():
                            raise ValueError(
                                f"'{param}' is not a parameter of {self.name}"
                            )
                        self.parameters.properties[param].description = value
                else:
                    self.parameters = parameters
            else:
                self.parameters = tool_info.parameters
        else:
            self.name = name
            self.description = description
            self.parameters = parameters

        # behavioral attributes
        self.parallel = parallel
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


def tool_defs(
    tools: list[Tool] | list[ToolDef] | list[Tool | ToolDef],
) -> list[ToolDef]:
    return [tool_def(tool) if isinstance(tool, Tool) else tool for tool in tools]


def tool_def(tool: Tool) -> ToolDef:
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
    return ToolDef(
        tool=tool,
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
