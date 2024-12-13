from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.rich import lines_display
from inspect_ai._util.transcript import transcript_markdown
from inspect_ai.util._trace import trace_enabled, trace_panel

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool
from ._render import messages_preceding_assistant, render_tool_calls

MESSAGE_TITLE = "Message"


def trace_tool_mesage(message: ChatMessageTool) -> None:
    if trace_enabled():
        # truncate output to 100 lines
        output = message.error.message if message.error else message.text.strip()
        content = lines_display(output, 100)

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
                content=transcript_markdown(m.text, escape=True),
            )

        # start with assistant content
        content: list[RenderableType] = (
            [transcript_markdown(message.text, escape=True)] if message.text else []
        )

        # print tool calls
        if message.tool_calls:
            content.append(Text())
            content.extend(render_tool_calls(message.tool_calls))

        # print the assistant message
        trace_panel(title="Assistant", content=content)
