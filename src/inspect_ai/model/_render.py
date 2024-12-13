from rich.console import RenderableType

from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_transcript import transcript_tool_call

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool


def messages_preceding_assistant(messages: list[ChatMessage]) -> list[ChatMessage]:
    preceding: list[ChatMessage] = []
    for m in reversed(messages):
        if not isinstance(m, ChatMessageTool | ChatMessageAssistant):
            preceding.append(m)
        else:
            break
    return list(reversed(preceding))


def render_tool_calls(tool_calls: list[ToolCall]) -> list[RenderableType]:
    formatted_calls: list[RenderableType] = []

    for call in tool_calls:
        formatted_calls.extend(transcript_tool_call(call))

    return formatted_calls
