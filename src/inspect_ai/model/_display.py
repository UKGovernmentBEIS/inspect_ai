from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.rich import lines_display
from inspect_ai._util.transcript import transcript_markdown, transcript_reasoning
from inspect_ai.util._conversation import conversation_panel
from inspect_ai.util._display import display_type

from ._chat_message import ChatMessage, ChatMessageAssistant, ChatMessageTool
from ._render import messages_preceding_assistant, render_tool_calls

MESSAGE_TITLE = "Message"


def display_conversation_message(message: ChatMessage) -> None:
    if display_type() == "conversation":
        if isinstance(message, ChatMessageTool):
            display_conversation_tool_message(message)
        elif isinstance(message, ChatMessageAssistant):
            display_conversation_assistant_message(message)
        else:
            conversation_panel(
                title=message.role.capitalize(),
                content=transcript_markdown(message.text, escape=True),
            )


def display_conversation_tool_message(message: ChatMessageTool) -> None:
    if display_type() == "conversation":
        # truncate output to 100 lines
        output = (
            message.error.message.strip() if message.error else message.text.strip()
        )
        if output:
            content = lines_display(output, 50)

            conversation_panel(
                title=f"Tool Output: {message.function}",
                content=content,
            )


def display_conversation_assistant_message(message: ChatMessageAssistant) -> None:
    # build content
    content: list[RenderableType] = []

    # deal with plain text or with content blocks
    if isinstance(message.content, str):
        content.extend([transcript_markdown(message.text.strip(), escape=True)])
    else:
        for c in message.content:
            if isinstance(c, ContentReasoning):
                content.extend(transcript_reasoning(c))
            elif isinstance(c, ContentText) and c.text:
                content.extend([transcript_markdown(c.text.strip(), escape=True)])

    # print tool calls
    if message.tool_calls:
        if content:
            content.append(Text())
        content.extend(render_tool_calls(message.tool_calls))

    # print the assistant message
    conversation_panel(title="Assistant", content=content)


def display_conversation_assistant(
    input: list[ChatMessage], message: ChatMessageAssistant
) -> None:
    if display_type() == "conversation":
        # print precding messages that aren't tool or assistant
        for m in messages_preceding_assistant(input):
            conversation_panel(
                title=m.role.capitalize(),
                content=transcript_markdown(m.text, escape=True),
            )

        # show assistant message
        display_conversation_assistant_message(message)


def display_conversation_assistant_error(error: Exception) -> None:
    if display_type() == "conversation":
        conversation_panel(title="Assistant", content=repr(error))
