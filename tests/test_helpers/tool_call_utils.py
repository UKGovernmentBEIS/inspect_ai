from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import ToolEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool import ToolCall


def get_tool_call(messages: list[ChatMessage], tool: str) -> ToolCall | None:
    tool_calls = get_tool_calls(messages, tool)
    if tool_calls:
        return tool_calls[0]
    else:
        return None


def get_tool_calls(messages: list[ChatMessage], tool: str) -> list[ToolCall]:
    tool_call_messages = [
        message
        for message in messages
        if isinstance(message, ChatMessageAssistant) and message.tool_calls
    ]
    tool_calls: list[ToolCall] = []
    for message in tool_call_messages:
        tool_calls.extend(
            [
                tool_call
                for tool_call in (message.tool_calls or [])
                if tool_call.function == tool
            ]
        )
    return tool_calls


def get_tool_response(
    messages: list[ChatMessage], tool_call: ToolCall
) -> ChatMessageTool | None:
    tool_messages = [
        message for message in messages if isinstance(message, ChatMessageTool)
    ]
    tool_response = next(
        (message for message in tool_messages if message.tool_call_id == tool_call.id),
        None,
    )
    if tool_response:
        return tool_response
    else:
        return None


def get_tool_event(log: EvalLog) -> ToolEvent | None:
    if log.samples:
        return next(
            (event for event in log.samples[0].events if isinstance(event, ToolEvent)),
            None,
        )
    else:
        return None
