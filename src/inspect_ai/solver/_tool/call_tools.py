from typing import Any

from inspect_ai._util.error import exception_message
from inspect_ai._util.registry import registry_info
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ToolCall

from .._task_state import TaskState
from .tool import TOOL_PARAMS, ToolError
from .tool_def import ToolDef, tool_defs


async def call_tools(state: TaskState) -> TaskState:
    """Resolve pending tool calls in the TaskState.

    If the last message is of type ChatMessageAssistant and it
    includes tool calls, resolve the tool calls by calling the
    underlying Python functions and appending the appropriate
    ChatMessageTool messages to the state.

    Args:
       state: Current TaskState

    Returns:
       Task state with tool calls resolved.
    """
    # get last message
    message = state.messages[-1]

    # resolve tool calls if necessary
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        tdefs = tool_defs(state.tools)
        for tool_call in message.tool_calls:
            tool_error: str | None = None
            try:
                result = await call_tool(tdefs, tool_call, state.metadata)
            except ToolError as ex:
                result = ""
                tool_error = ex.message

            if isinstance(result, tuple):
                result, metadata = result
                state.metadata.update(metadata)

            state.messages.append(
                ChatMessageTool(
                    content=result if isinstance(result, list) else str(result),
                    tool_error=tool_error,
                    tool_call_id=tool_call.id,
                )
            )

    # return state
    return state


async def call_tool(
    tools: list[ToolDef], call: ToolCall, metadata: dict[str, Any]
) -> Any:
    # if there was an error parsing the ToolCall, raise that
    if call.parse_error:
        raise ToolError(call.parse_error)

    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        raise ToolError(f"Tool {call.function} not found")

    # resolve metadata params and prepend to arguments
    tool_params: dict[str, str] = registry_info(tool_def.tool).metadata.get(
        TOOL_PARAMS, {}
    )
    resolved_params: dict[str, Any] = {}
    for name, value in tool_params.items():
        key = value.removeprefix("metadata.")
        resolved = metadata.get(key, None)
        if resolved is None:
            raise ValueError(f"Metadata value '{key}' not found for tool parameter")
        resolved_params[name] = resolved
    arguments = resolved_params | call.arguments

    # call the tool
    try:
        return await tool_def.tool(**arguments)
    except TypeError as ex:
        raise ToolError(exception_message(ex))
