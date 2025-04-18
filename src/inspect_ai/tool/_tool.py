import re
from functools import wraps
from logging import getLogger
from typing import (
    Any,
    Callable,
    ParamSpec,
    Protocol,
    cast,
    overload,
    runtime_checkable,
)

from inspect_ai._util.content import (
    ContentAudio,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_add,
    registry_name,
    registry_tag,
)

from ._tool_call import ToolCallModelInput, ToolCallViewer

logger = getLogger(__name__)


ToolResult = (
    str
    | int
    | float
    | bool
    | ContentText
    | ContentReasoning
    | ContentImage
    | ContentAudio
    | ContentVideo
    | list[ContentText | ContentReasoning | ContentImage | ContentAudio | ContentVideo]
)
"""Valid types for results from tool calls."""


class ToolError(Exception):
    """Exception thrown from tool call.

    If you throw a `ToolError` form within a tool call,
    the error will be reported to the model for further
    processing (rather than ending the sample). If you want
    to raise a fatal error from a tool call use an appropriate
    standard exception type (e.g. `RuntimeError`, `ValueError`, etc.)
    """

    def __init__(self, message: str) -> None:
        """Create a ToolError.

        Args:
          message: Error message to report to the model.
        """
        super().__init__(message)
        self.message = message


class ToolParsingError(ToolError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ToolApprovalError(ToolError):
    def __init__(self, message: str | None) -> None:
        super().__init__(message or "Tool call not approved.")


@runtime_checkable
class Tool(Protocol):
    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ToolResult:
        r"""Additional tool that an agent can use to solve a task.

        Args:
          *args: Arguments for the tool.
          **kwargs: Keyword arguments for the tool.

        Returns:
            Result of tool call.

        Examples:
          ```python
          @tool
          def add() -> Tool:
              async def execute(x: int, y: int) -> int:
                  return x + y

              return execute
          ```
        """
        ...


@runtime_checkable
class ToolSource(Protocol):
    """Protocol for dynamically providing a set of tools."""

    async def tools(self) -> list[Tool]:
        """Retrieve tools from tool source.

        Returns:
            List of tools
        """
        ...


P = ParamSpec("P")


def tool_register(tool: Callable[P, Tool], name: str) -> Callable[P, Tool]:
    r"""Register a function or class as a tool.

    Args:
        tool (ToolType):
            Tool function or a class derived from Tool.
        docstring (Docstring): Docstring for the tool. Used to extract arg descriptions.
        name (str): Name of tool (Optional, defaults to object name)

    Returns:
        Tool with registry attributes.
    """
    registry_add(
        tool,
        RegistryInfo(type="tool", name=name),
    )
    return tool


@overload
def tool(func: Callable[P, Tool]) -> Callable[P, Tool]: ...


@overload
def tool() -> Callable[[Callable[P, Tool]], Callable[P, Tool]]: ...


@overload
def tool(
    *,
    name: str | None = None,
    viewer: ToolCallViewer | None = None,
    model_input: ToolCallModelInput | None = None,
    parallel: bool = True,
    prompt: str | None = None,
) -> Callable[[Callable[P, Tool]], Callable[P, Tool]]: ...


def tool(
    func: Callable[P, Tool] | None = None,
    *,
    name: str | None = None,
    viewer: ToolCallViewer | None = None,
    model_input: ToolCallModelInput | None = None,
    parallel: bool = True,
    prompt: str | None = None,
) -> Callable[P, Tool] | Callable[[Callable[P, Tool]], Callable[P, Tool]]:
    r"""Decorator for registering tools.

    Args:
        func: Tool function
        name: Optional name for tool. If the decorator has no name
            argument then the name of the tool creation function
            will be used as the name of the tool.
        viewer: Provide a custom view of tool call and context.
        model_input: Provide a custom function for playing back tool results as model input.
        parallel: Does this tool support parallel execution? (defaults to `True`).
        prompt: Deprecated (provide all descriptive information about
            the tool within the tool function's doc comment)


    Returns:
        Tool with registry attributes.

    Examples:
        ```python
        @tool
        def add() -> Tool:
            async def execute(x: int, y: int) -> int:
                return x + y

            return execute
        ```
    """
    if prompt:
        from inspect_ai._util.logger import warn_once

        warn_once(
            logger,
            "The prompt parameter is deprecated (please relocate "
            + "to the tool function's description doc comment)",
        )
        prompt = re.sub(r"\s+", " ", prompt)

    def create_tool_wrapper(tool_type: Callable[P, Tool]) -> Callable[P, Tool]:
        # determine the name (explicit or implicit from object)
        tool_name = registry_name(
            tool_type, name if name else getattr(tool_type, "__name__")
        )

        # wrap instantiations of scorer so they carry registry info and metrics
        @wraps(tool_type)
        def tool_wrapper(*args: P.args, **kwargs: P.kwargs) -> Tool:
            # create the tool
            tool = tool_type(*args, **kwargs)

            # this might already have registry info, in that case
            # capture it and use it as defaults
            from inspect_ai.tool._tool_def import tool_registry_info

            tool_parallel = parallel
            tool_viewer = viewer
            tool_model_input = model_input
            if is_registry_object(tool):
                _, _, reg_parallel, reg_viewer, reg_model_input = tool_registry_info(
                    tool
                )
                tool_parallel = parallel and reg_parallel
                tool_viewer = viewer or reg_viewer
                tool_model_input = model_input or reg_model_input

            # tag the object
            registry_tag(
                tool_type,
                tool,
                RegistryInfo(
                    type="tool",
                    name=tool_name,
                    metadata={
                        TOOL_PROMPT: prompt,
                        TOOL_PARALLEL: tool_parallel,
                        TOOL_VIEWER: tool_viewer,
                        TOOL_MODEL_INPUT: (
                            tool_model_input
                            or getattr(tool, TOOL_INIT_MODEL_INPUT, None)
                        ),
                    },
                ),
                *args,
                **kwargs,
            )
            return tool

        # register
        return tool_register(cast(Callable[P, Tool], tool_wrapper), tool_name)

    if func is not None:
        return create_tool_wrapper(func)
    else:
        return create_tool_wrapper


TOOL_PROMPT = "prompt"
TOOL_PARALLEL = "parallel"
TOOL_VIEWER = "viewer"
TOOL_MODEL_INPUT = "model_input"


TOOL_INIT_MODEL_INPUT = "__TOOL_INIT_MODEL_INPUT__"
