from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text

from inspect_ai._util.format import format_function_call
from inspect_ai.util._trace import trace_panel

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool

MESSAGE_TITLE = "Message"


def trace_tool_mesage(message: ChatMessageTool) -> None:
    trace_panel(
        title=MESSAGE_TITLE,
        subtitle=f"Tool ouptut: {message.function}",
        content=message.error.message if message.error else message.text.strip(),
    )


def trace_assistant_message(
    input: list[ChatMessage], message: ChatMessageAssistant
) -> None:
    # print precding messages that aren't tool or assistant
    preceding: list[ChatMessage] = []
    for m in reversed(input):
        if not isinstance(m, ChatMessageTool | ChatMessageAssistant):
            preceding.append(m)
        else:
            break
    for m in reversed(preceding):
        trace_panel(
            title=MESSAGE_TITLE,
            subtitle=m.role.capitalize(),
            content=m.text,
        )

    # start with assistant content
    content: list[RenderableType] = [message.text]

    # print tool calls
    if message.tool_calls:
        tool_calls: list[str] = []
        for call in message.tool_calls:
            tool_calls.append(format_function_call(call.function, call.arguments))
        content.append(Text())
        content.append(
            Markdown("```python\n" + "\n\n".join(tool_calls) + "\n```\n"),
        )

    # print the assistant message (TODO: tool call)
    trace_panel(title=MESSAGE_TITLE, subtitle="Assistant", content=content)
