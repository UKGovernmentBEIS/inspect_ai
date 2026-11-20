from pydantic import JsonValue
from rich.console import RenderableType
from rich.highlighter import ReprHighlighter
from rich.markup import escape
from rich.rule import Rule
from rich.text import Text

from inspect_ai._util.transcript import transcript_markdown
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    default_tool_call_viewer,
    substitute_tool_call_content,
)
from inspect_ai.util._display import display_type

HUMAN_APPROVED = "Human operator approved tool call."
HUMAN_REJECTED = "Human operator rejected the tool call."
HUMAN_TERMINATED = "Human operator asked that the sample be terminated."
HUMAN_ESCALATED = "Human operator escalated the tool call approval."


def arguments_view(call: ToolCall, view: ToolCallView) -> ToolCallContent | None:
    """The default view of `call`, to show beneath `view` unless it is that view.

    A tool's own viewer writes Markdown that a renderer may show only part of,
    so the person approving the call also sees every argument as a Python
    literal, in a block of its own that the view cannot affect. The block is
    left out when the view's content is the call's default view, and for a
    call with no arguments.
    """
    if not call.arguments:
        return None
    content = default_tool_call_viewer(call).call
    if content is None:
        return None
    if (
        view.call is not None
        and view.call.format == content.format
        and view.call.content == content.content
    ):
        return None
    return content.model_copy(update={"title": "Full tool call"})


def render_tool_approval(
    message: str,
    view: ToolCallView,
    arguments: dict[str, JsonValue] | None = None,
    call: ToolCall | None = None,
) -> list[RenderableType]:
    renderables: list[RenderableType] = []
    text_highlighter = ReprHighlighter()
    all_arguments = arguments_view(call, view) if call is not None else None

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

    # every argument, unless the view is the call's default view
    if all_arguments:
        if message or view.context or view.call:
            renderables.append(Rule("", style="#282c34", align="left", characters="․"))
        renderables.append(Text())
        add_view_content(all_arguments)
        renderables.append(Text())

    return renderables
