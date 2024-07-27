import asyncio
from typing import Any

from inspect_ai._util.error import exception_message
from inspect_ai.tool import Tool, ToolCall, ToolError
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.tool._tool_call import ToolCallError
from inspect_ai.tool._tool_def import ToolDef, tool_defs

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
