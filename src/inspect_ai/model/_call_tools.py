import asyncio
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    cast,
)

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.error import exception_message
from inspect_ai._util.registry import registry_info
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolInfo
from inspect_ai.tool._tool import TOOL_PROMPT, ToolParsingError
from inspect_ai.tool._tool_call import ToolCallError
from inspect_ai.tool._tool_info import ToolParams, parse_tool_info

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
            result: Any = ""
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

            # massage result, leave list[Content] alone, convert all other
            # types to string as that is what the model APIs accept
            if isinstance(result, list) and (
                isinstance(result[0], ContentText | ContentImage)
            ):
                content: str | list[Content] = result
            else:
                content = str(result)

            return ChatMessageTool(
                content=content,
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

    parameters: ToolParams
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
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                )
                for tool in tdefs
            ]
    else:
        return []


def tool_defs(tools: list[Tool]) -> list[ToolDef]:
    return [tool_def(tool) for tool in tools]


def tool_def(tool: Tool) -> ToolDef:
    name, prompt = tool_name_and_prompt(tool)
    tool_info = parse_tool_info(tool)

    # build params
    return ToolDef(
        name=name,
        description=tool_info.description,
        prompt=prompt,
        parameters=tool_info.parameters,
        tool=tool,
    )


def tool_name_and_prompt(tool: Tool) -> tuple[str, str | None]:
    tool_registry_info = registry_info(tool)
    name = tool_registry_info.name.split("/")[-1]
    prompt = tool_registry_info.metadata.get(TOOL_PROMPT, None)
    return name, prompt
