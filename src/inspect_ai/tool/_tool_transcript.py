from pydantic import JsonValue
from rich.console import RenderableType
from rich.text import Text
from typing_extensions import Protocol

from inspect_ai._util.transcript import transcript_function, transcript_markdown

from ._tool_call import ToolCallContent


class TranscriptToolCall(Protocol):
    function: str
    arguments: dict[str, JsonValue]
    view: ToolCallContent | None


def transcript_tool_call(call: TranscriptToolCall) -> list[RenderableType]:
    content: list[RenderableType] = []
    if call.view:
        if call.view.title:
            content.append(Text.from_markup(f"[bold]{call.view.title}[/bold]\n"))
        if call.view.format == "markdown":
            content.append(transcript_markdown(call.view.content))
        else:
            content.append(call.view.content)
    else:
        content.append(transcript_function(call.function, call.arguments))
    return content
