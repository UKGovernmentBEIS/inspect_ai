from copy import copy
from typing import (
    Any,
    Callable,
    NamedTuple,
    Sequence,
)

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_info,
    set_registry_info,
    set_registry_params,
)

from ._tool import (
    TOOL_MODEL_INPUT,
    TOOL_PARALLEL,
    TOOL_PROMPT,
    TOOL_VIEWER,
    Tool,
    ToolSource,
)
from ._tool_call import ToolCallModelInput, ToolCallViewer
from ._tool_description import (
    ToolDescription,
    set_tool_description,
    tool_description,
)
from ._tool_info import parse_tool_info
from ._tool_params import ToolParam, ToolParams


class ToolDef:
    """Tool definition."""

    def __init__(
        self,
        tool: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        parameters: dict[str, str] | ToolParams | None = None,
        parallel: bool | None = None,
        viewer: ToolCallViewer | None = None,
        model_input: ToolCallModelInput | None = None,
    ) -> None:
        """Create a tool definition.

        Args:
          tool: Callable to execute tool.
          name: Name of tool. Discovered automatically if not specified.
          description: Description of tool. Discovered automatically
            by parsing doc comments if not specified.
          parameters: Tool parameter descriptions and types.
             Discovered automatically by parsing doc comments if not specified.
          parallel: Does the tool support parallel execution
             (defaults to True if not specified)
          viewer: Optional tool call viewer implementation.
          model_input: Optional function that determines how
              tool call results are played back as model input.

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
            self.model_input = model_input or tdef.model_input

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
            self.model_input = model_input

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

    model_input: ToolCallModelInput | None
    """Custom model input presenter for tool calls."""

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


async def tool_defs(
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
) -> list[ToolDef]:
    if isinstance(tools, ToolSource):
        tools = await tools.tools()

    tool_defs: list[ToolDef] = []
    for tool in tools:
        if isinstance(tool, ToolSource):
            tool_defs.extend([ToolDef(t) for t in await tool.tools()])
        elif not isinstance(tool, ToolDef):
            tool_defs.append(ToolDef(tool))
        else:
            tool_defs.append(tool)
    return tool_defs


class ToolDefFields(NamedTuple):
    name: str
    description: str
    parameters: ToolParams
    parallel: bool
    viewer: ToolCallViewer | None
    model_input: ToolCallModelInput | None


def tool_def_fields(tool: Tool) -> ToolDefFields:
    # get tool_info
    name, prompt, parallel, viewer, model_input = tool_registry_info(tool)
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
    validate_tool_parameters(name, tool_info.parameters.properties)

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
        model_input=model_input,
    )


def tool_registry_info(
    tool: Tool,
) -> tuple[str, str | None, bool, ToolCallViewer | None, ToolCallModelInput | None]:
    info = registry_info(tool)
    name = info.name.split("/")[-1]
    prompt = info.metadata.get(TOOL_PROMPT, None)
    parallel = info.metadata.get(TOOL_PARALLEL, True)
    viewer = info.metadata.get(TOOL_VIEWER, None)
    model_input = info.metadata.get(TOOL_MODEL_INPUT, None)
    return name, prompt, parallel, viewer, model_input


def validate_tool_parameters(tool_name: str, parameters: dict[str, ToolParam]) -> None:
    # validate that we have types/descriptions for paramters
    for param_name, param in parameters.items():

        def raise_not_provided_error(
            context: str,
            # Use the default value trick to avoid Python's late binding of
            # closures issue.
            # see: https://docs.python.org/3/faq/programming.html#why-do-lambdas-defined-in-a-loop-with-different-values-all-return-the-same-result
            bound_name: str = param_name,
        ) -> None:
            raise ValueError(
                f"{context} provided for parameter '{bound_name}' of function '{tool_name}'."
            )

        if not param.description:
            raise_not_provided_error("Description not")
