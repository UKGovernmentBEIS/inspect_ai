import asyncio
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
from inspect_ai.tool._tool import TOOL_PROMPT, ToolParsingError
from inspect_ai.tool._tool_call import ToolCallError

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

        async def call_tool_task(call: ToolCall) -> ChatMessageTool:
            result = ""
            tool_error: ToolCallError | None = None
            try:
                result = await call_tool(tdefs, call)
            except TimeoutError:
                tool_error = ToolCallError(
                    "timeout", "Command timed out before completing."
                )
            except UnicodeDecodeError as ex:
                tool_error = ToolCallError(
                    "unicode_decode",
                    f"Error decoding bytes to {ex.encoding}: {ex.reason}",
                )
            except PermissionError as ex:
                message = f"{ex.strerror}."
                if isinstance(ex.filename, str):
                    message = f"{message} Filename '{ex.filename}'."
                tool_error = ToolCallError("permission", message)
            except FileNotFoundError as ex:
                tool_error = ToolCallError(
                    "file_not_found",
                    f"File '{ex.filename}' was not found.",
                )
            except ToolParsingError as ex:
                tool_error = ToolCallError("parsing", ex.message)
            except ToolError as ex:
                tool_error = ToolCallError("unknown", ex.message)

            return ChatMessageTool(
                content=result if isinstance(result, list) else str(result),
                tool_call_id=call.id,
                error=tool_error,
            )

        tasks = [call_tool_task(call) for call in message.tool_calls]
        return await asyncio.gather(*tasks)

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
        raise ToolParsingError(call.parse_error)

    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        raise ToolParsingError(f"Tool {call.function} not found")

    # call the tool
    try:
        return await tool_def.tool(**call.arguments)
    except TypeError as ex:
        raise ToolParsingError(exception_message(ex))


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
