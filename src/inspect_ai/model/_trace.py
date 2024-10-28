from rich.console import RenderableType
from rich.text import Text

from inspect_ai.util._trace import trace_enabled, trace_panel

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool
from ._render import messages_preceding_assistant, render_tool_calls

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
        for m in messages_preceding_assistant(input):
            trace_panel(
                title=m.role.capitalize(),
                content=m.text,
            )

        # start with assistant content
        content: list[RenderableType] = [message.text] if message.text else []

        # print tool calls
        if message.tool_calls:
            content.append(Text())
            content.append(render_tool_calls(message.tool_calls))

        # print the assistant message
        trace_panel(title="Assistant", content=content)
