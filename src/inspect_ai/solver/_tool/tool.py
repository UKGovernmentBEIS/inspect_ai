import re
from typing import (
    Any,
    Callable,
    Protocol,
    Tuple,
    TypeVar,
    cast,
    runtime_checkable,
)

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

ToolResult = str | int | float | bool | Tuple[str | int | float | bool, dict[str, Any]]


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
            Single value or a tuple containing the value and
            metadata to add to the task state
        """
        ...


ToolType = TypeVar("ToolType", Callable[..., Tool], type[Tool])
r"""Tool type.

Valid tool types include:
 - Functions that return a Tool
 - Classes derivied from Tool
"""


def tool_register(tool: ToolType, name: str) -> ToolType:
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


def tool(
    prompt: str | None = None,
    params: dict[str, str] = {},
    name: str | None = None,
) -> Callable[[Callable[..., Tool]], Callable[..., Tool]]:
    r"""Decorator for registering tools.

    Args:
        prompt (str):
            System prompt associated with this tool (provides
            guideance to the LLM on how to use the tool)
        name (str | None):
            Optional name for tool. If the decorator has no name
            argument then the name of the underlying ToolType
            object will be used to automatically assign a name.
        params (params): Parameters to be passed automatically to
            the tool. This currently allows only for mapping metadata
            fields from the input / task state onto parameters. These
            models precede other parameters that are used by the
            model.
            For example:

            ```python
            @tool(params = dict(color = "metadata.color"))
            def mytool():
                async def execute(color: str, cut: str):
                    ...

                return execute

            ```

    Returns:
        Tool with registry attributes.
    """
    # remove spurous spacing from prompt (can occur if a multline string
    # is used to specify the prompt)
    if prompt:
        prompt = re.sub(r"\s+", " ", prompt)

    def wrapper(tool_type: ToolType) -> ToolType:
        # determine the name (explicit or implicit from object)
        tool_name = registry_name(
            tool_type, name if name else getattr(tool_type, "__name__")
        )

        # wrap instatiations of scorer so they carry registry info and metrics
        def tool_wrapper(*args: Any, **kwargs: Any) -> Tool:
            tool = tool_type(*args, **kwargs)
            registry_tag(
                tool_type,
                tool,
                RegistryInfo(
                    type="tool",
                    name=tool_name,
                    metadata={TOOL_PROMPT: prompt, TOOL_PARAMS: params},
                ),
                *args,
                **kwargs,
            )
            return tool

        # register the scorer
        return tool_register(cast(ToolType, tool_wrapper), tool_name)

    return wrapper


TOOL_PROMPT = "prompt"
TOOL_PARAMS = "params"
