import inspect
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    cast,
)

from docstring_parser import Docstring, DocstringParam

from inspect_ai._util.docstring import parse_docstring
from inspect_ai._util.error import exception_message
from inspect_ai._util.json import python_type_to_json_type
from inspect_ai._util.registry import registry_info
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolInfo, ToolParam
from inspect_ai.tool._tool import TOOL_PROMPT

from ._chat_message import ChatMessageAssistant, ChatMessageTool


async def call_tools(
    message: ChatMessageAssistant, tools: list[Tool]
) -> list[ChatMessageTool]:
    """Perform tool calls in assistant message.

    Args:
       message: Assistant message
       tools: Available tools

    Returns:
       List of tool calls
    """
    if message.tool_calls:
        tdefs = tool_defs(tools)
        tool_messages: list[ChatMessageTool] = []
        for tool_call in message.tool_calls:
            tool_error: str | None = None
            try:
                result = await call_tool(tdefs, tool_call)
            except ToolError as ex:
                result = ""
                tool_error = ex.message

            # there may be some tool still returning tuple
            if isinstance(result, tuple):
                result, _ = result

            tool_messages.append(
                ChatMessageTool(
                    content=result if isinstance(result, list) else str(result),
                    tool_error=tool_error,
                    tool_call_id=tool_call.id,
                )
            )

        # return state
        return tool_messages
    else:
        return []


@dataclass
class ToolDef:
    name: str
    """Tool name."""

    description: str
    """Tool description."""

    params: list[ToolParam]
    """Tool parameters"""

    prompt: str | None
    """System prompt text to guide model usage of tool."""

    tool: Callable[..., Any]
    """Callable to execute tool."""


async def call_tool(tools: list[ToolDef], call: ToolCall) -> Any:
    # if there was an error parsing the ToolCall, raise that
    if call.parse_error:
        raise ToolError(call.parse_error)

    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        raise ToolError(f"Tool {call.function} not found")

    # call the tool
    try:
        return await tool_def.tool(**call.arguments)
    except TypeError as ex:
        raise ToolError(exception_message(ex))


def tools_info(tools: list[Tool] | list[ToolInfo]) -> list[ToolInfo]:
    if len(tools) > 0:
        if isinstance(tools[0], ToolInfo):
            return cast(list[ToolInfo], tools)
        else:
            tdefs = tool_defs(cast(list[Tool], tools))
            return [
                ToolInfo(
                    name=tool.name, description=tool.description, params=tool.params
                )
                for tool in tdefs
            ]
    else:
        return []


def tool_defs(tools: list[Tool]) -> list[ToolDef]:
    return [tool_def(tool) for tool in tools]


def tool_def(tool: Tool) -> ToolDef:
    tool_info = registry_info(tool)
    name = tool_info.name.split("/")[-1]
    docstring = tool_docstring(tool)

    # build params
    params = [tool_param(param) for param in docstring.params]
    return ToolDef(
        name=name,
        description=str(docstring.short_description),
        prompt=tool_info.metadata.get(TOOL_PROMPT, None),
        params=params,
        tool=tool,
    )


def tool_param(param: DocstringParam) -> ToolParam:
    return ToolParam(
        name=param.arg_name,
        type=python_type_to_json_type(param.type_name),
        description=str(param.description),
        optional=param.is_optional is True,
    )


def tool_docstring(tool: Tool) -> Docstring:
    docstring = parse_docstring(inspect.getdoc(tool))
    # We need tool and parameter descriptions to pass to the agent
    assert (
        docstring.short_description is not None
    ), "Tool must have a short description in the docstring"
    params = list(inspect.signature(tool).parameters.keys())
    if len(params) > 0:
        for param in params:
            assert param in [
                docstring_param.arg_name for docstring_param in docstring.params
            ], f"Parameter {param} must be documented in the docstring"
        assert [
            docstring_param.description != "" for docstring_param in docstring.params
        ], "All tool parameters must have a description"
    return docstring
