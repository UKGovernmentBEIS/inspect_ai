from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text

from inspect_ai._util.format import format_function_call
from inspect_ai.util._trace import trace_enabled, trace_panel

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool

MESSAGE_TITLE = "Message"


def trace_tool_mesage(message: ChatMessageTool) -> None:
    if trace_enabled():
        # truncate output to 100 lines
        MAX_LINES = 100
        output = message.error.message if message.error else message.text.strip()
        lines = output.splitlines()
        if len(lines) > MAX_LINES:
            content: list[RenderableType] = ["\n".join(lines[0:MAX_LINES])]
            content.append(Text())
            content.append(
                Text.from_markup(
                    f"[italic]Output truncated ({len(lines) - MAX_LINES} additional lines)...[/italic]"
                )
            )
        else:
            content = [output]

        trace_panel(
            title=f"Tool Output: {message.function}",
            content=content,
        )


def trace_assistant_message(
    input: list[ChatMessage], message: ChatMessageAssistant
) -> None:
    if trace_enabled():
        # print precding messages that aren't tool or assistant
        preceding: list[ChatMessage] = []
        for m in reversed(input):
            if not isinstance(m, ChatMessageTool | ChatMessageAssistant):
                preceding.append(m)
            else:
                break
        for m in reversed(preceding):
            trace_panel(
                title=m.role.capitalize(),
                content=m.text,
            )

        # start with assistant content
        content: list[RenderableType] = [message.text] if message.text else []

        # print tool calls
        if message.tool_calls:
            if content:
                content.append(Text())
            tool_calls: list[str] = []
            for call in message.tool_calls:
                tool_calls.append(format_function_call(call.function, call.arguments))
            content.append(
                Markdown("```python\n" + "\n\n".join(tool_calls) + "\n```\n"),
            )

        # print the assistant message
        trace_panel(title="Assistant", content=content)
