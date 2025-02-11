from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.rich import lines_display
from inspect_ai._util.transcript import transcript_markdown, transcript_reasoning
from inspect_ai.util._conversation import conversation_panel
from inspect_ai.util._display import display_type

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool
from ._render import messages_preceding_assistant, render_tool_calls

MESSAGE_TITLE = "Message"


def conversation_tool_mesage(message: ChatMessageTool) -> None:
    if display_type() == "conversation":
        # truncate output to 100 lines
        output = (
            message.error.message.strip() if message.error else message.text.strip()
        )
        if output:
            content = lines_display(output, 100)

            conversation_panel(
                title=f"Tool Output: {message.function}",
                content=content,
            )


def conversation_assistant_message(
    input: list[ChatMessage], message: ChatMessageAssistant
) -> None:
    if display_type() == "conversation":
        # print precding messages that aren't tool or assistant
        for m in messages_preceding_assistant(input):
            conversation_panel(
                title=m.role.capitalize(),
                content=transcript_markdown(m.text, escape=True),
            )

        # build content
        content: list[RenderableType] = []

        # reasoning
        if message.reasoning:
            content.extend(transcript_reasoning(message.reasoning))

        # message text
        content.extend(
            [transcript_markdown(message.text, escape=True)] if message.text else []
        )

        # print tool calls
        if message.tool_calls:
            if content:
                content.append(Text())
            content.extend(render_tool_calls(message.tool_calls))

        # print the assistant message
        conversation_panel(title="Assistant", content=content)


def conversation_assistant_error(error: Exception) -> None:
    if display_type() == "conversation":
        conversation_panel(title="Assistant", content=repr(error))
