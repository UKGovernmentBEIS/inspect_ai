from pydantic import JsonValue
from rich.console import RenderableType
from rich.highlighter import ReprHighlighter
from rich.markup import escape
from rich.rule import Rule
from rich.text import Text

from inspect_ai._util.transcript import transcript_markdown
from inspect_ai.tool._tool_call import (
    ToolCallContent,
    ToolCallView,
    substitute_tool_call_content,
)
from inspect_ai.util._display import display_type

HUMAN_APPROVED = "Human operator approved tool call."
HUMAN_REJECTED = "Human operator rejected the tool call."
HUMAN_TERMINATED = "Human operator asked that the sample be terminated."
HUMAN_ESCALATED = "Human operator escalated the tool call approval."


def render_tool_approval(
    message: str, view: ToolCallView, arguments: dict[str, JsonValue] | None = None
) -> list[RenderableType]:
    renderables: list[RenderableType] = []
    text_highlighter = ReprHighlighter()

    # substitute placeholders in view content
    if arguments is not None:
        view = ToolCallView(
            context=substitute_tool_call_content(view.context, arguments)
            if view.context
            else None,
            call=substitute_tool_call_content(view.call, arguments)
            if view.call
            else None,
        )

    # ignore content if trace enabled
    message = message.strip() if display_type() != "conversation" else ""

    def add_view_content(view_content: ToolCallContent) -> None:
        if view_content.title:
            renderables.append(
                Text.from_markup(f"[bold]{escape(view_content.title)}[/bold]\n")
            )
        if view_content.format == "markdown":
            renderables.append(transcript_markdown(view_content.content))
        else:
            text_content = text_highlighter(Text(view_content.content))
            renderables.append(text_content)

    # assistant content (don't add if trace_enabled as we already have it in that case)
    if message:
        renderables.append(Text.from_markup("[bold]Assistant[/bold]\n"))
        renderables.append(Text(f"{message.strip()}"))

    # extra context provided by tool view
    if view.context:
        renderables.append(Text())
        add_view_content(view.context)
        renderables.append(Text())

    # tool call view
    if view.call:
        if message or view.context:
            renderables.append(Rule("", style="#282c34", align="left", characters="․"))
        renderables.append(Text())
        add_view_content(view.call)
        renderables.append(Text())

    return renderables
