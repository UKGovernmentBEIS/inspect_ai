from rich.console import RenderableType

from inspect_ai._util.format import format_function_call
from inspect_ai._util.transcript import transcript_markdown
from inspect_ai.tool._tool_call import ToolCall

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool


def messages_preceding_assistant(messages: list[ChatMessage]) -> list[ChatMessage]:
    preceding: list[ChatMessage] = []
    for m in reversed(messages):
        if not isinstance(m, ChatMessageTool | ChatMessageAssistant):
            preceding.append(m)
        else:
            break
    return list(reversed(preceding))


def render_tool_calls(tool_calls: list[ToolCall]) -> RenderableType:
    formatted_calls: list[str] = []
    for call in tool_calls:
        formatted_calls.append(format_function_call(call.function, call.arguments))
    return transcript_markdown("```python\n" + "\n\n".join(formatted_calls) + "\n```\n")
