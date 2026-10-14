from dataclasses import replace
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai._util.format import display_safe
from inspect_ai._util.rich import tool_result_display
from inspect_ai._util.transcript import transcript_markdown, transcript_reasoning
from inspect_ai.tool._tool_call import ToolCall
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
            content = tool_result_display(output, 50)

            conversation_panel(
                title=f"Tool Output: {message.function}",
                content=content,
            )


def display_conversation_assistant_message(message: ChatMessageAssistant) -> None:
    # The model's text, reasoning and tool calls are written to the terminal,
    # where a control character could move the cursor and overwrite what is
    # printed after them, such as a person's approval prompt for this turn;
    # `display_safe` shows each as a marker instead.

    # build content
    content: list[RenderableType] = []

    # deal with plain text or with content blocks
    if isinstance(message.content, str):
        content.extend([transcript_markdown(_shown(message.text).strip(), escape=True)])
    else:
        for c in message.content:
            if isinstance(c, ContentReasoning):
                content.extend(transcript_reasoning(_shown_reasoning(c)))
            elif isinstance(c, ContentText) and c.text:
                content.extend(
                    [transcript_markdown(_shown(c.text).strip(), escape=True)]
                )

    # print tool calls
    if message.tool_calls:
        if content:
            content.append(Text())
        content.extend(
            render_tool_calls([_shown_call(call) for call in message.tool_calls])
        )

    # print the assistant message
    conversation_panel(title="Assistant", content=content)


def display_conversation_assistant(
    input: list[ChatMessage], message: ChatMessageAssistant
) -> None:
    if display_type() == "conversation":
        # print precding messages that aren't tool or assistant
        for m in messages_preceding_assistant(input):
            display_conversation_message(m)

        # show assistant message
        display_conversation_assistant_message(message)


def display_conversation_assistant_error(error: Exception) -> None:
    if display_type() == "conversation":
        conversation_panel(title="Assistant", content=repr(error))


def _shown(text: str) -> str:
    return display_safe(text).text


def _shown_reasoning(reasoning: ContentReasoning) -> ContentReasoning:
    return reasoning.model_copy(
        update={
            "reasoning": _shown(reasoning.reasoning),
            "summary": _shown(reasoning.summary) if reasoning.summary else None,
        }
    )


def _shown_call(call: ToolCall) -> ToolCall:
    view = call.view
    if view is not None:
        view = view.model_copy(
            update={
                "title": _shown(view.title) if view.title else None,
                "content": _shown(view.content),
            }
        )
    return replace(
        call,
        function=_shown(call.function),
        arguments=_shown_value(call.arguments),
        view=view,
    )


def _shown_value(value: Any) -> Any:
    if isinstance(value, str):
        return _shown(value)
    if isinstance(value, dict):
        return {_shown(str(k)): _shown_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_shown_value(v) for v in value]
    return value
