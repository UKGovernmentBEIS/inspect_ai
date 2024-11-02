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

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

from . import Content
from ._tool_call import ToolCallViewer

logger = getLogger(__name__)


ToolResult = str | int | float | bool | list[Content]


class ToolError(Exception):
    def __init__(self, message: str) -> None:
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
            *args (Any): Arguments for the tool.
            **kwargs (Any): Keyword arguments for the tool.

        Returns:
            Result of tool call.
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
    parallel: bool = True,
    prompt: str | None = None,
) -> Callable[[Callable[P, Tool]], Callable[P, Tool]]: ...


def tool(
    func: Callable[P, Tool] | None = None,
    *,
    name: str | None = None,
    viewer: ToolCallViewer | None = None,
    parallel: bool = True,
    prompt: str | None = None,
) -> Callable[P, Tool] | Callable[[Callable[P, Tool]], Callable[P, Tool]]:
    r"""Decorator for registering tools.

    Args:
        func (ToolType | None): Tool function
        name (str | None):
            Optional name for tool. If the decorator has no name
            argument then the name of the tool creation function
            will be used as the name of the tool.
        viewer (ToolCallViewer | None): Provide a custom view
            of tool call and context.
        parallel (bool):
            Does this tool support parallel execution?
            (defaults to True).
        prompt (str):
            Deprecated (provide all descriptive information about
            the tool within the tool function's doc comment)


    Returns:
        Tool with registry attributes.
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
            tool = tool_type(*args, **kwargs)
            registry_tag(
                tool_type,
                tool,
                RegistryInfo(
                    type="tool",
                    name=tool_name,
                    metadata={
                        TOOL_PROMPT: prompt,
                        TOOL_PARALLEL: parallel,
                        TOOL_VIEWER: viewer,
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
