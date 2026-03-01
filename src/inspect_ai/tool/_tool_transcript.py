import re

from pydantic import JsonValue
from rich.console import RenderableType
from rich.markup import escape
from rich.text import Text
from typing_extensions import Protocol

from inspect_ai._util.transcript import transcript_function, transcript_markdown

from ._tool_call import ToolCallContent, substitute_tool_call_content


class TranscriptToolCall(Protocol):
    function: str
    arguments: dict[str, JsonValue]
    view: ToolCallContent | None


def transcript_tool_call(call: TranscriptToolCall) -> list[RenderableType]:
    content: list[RenderableType] = []
    if call.view:
        view = substitute_tool_call_content(call.view, call.arguments)
        if view.title:
            content.append(Text.from_markup(f"[bold]{escape(view.title)}[/bold]\n"))
        if view.format == "markdown":
            content.append(transcript_markdown(_collapse_details(view.content)))
        else:
            content.append(view.content)
    else:
        content.append(transcript_function(call.function, call.arguments))
    return content


def _collapse_details(text: str) -> str:
    """Replace <details> blocks with just their <summary> content."""

    def replace_details(m: re.Match[str]) -> str:
        summary_match = re.search(r"<summary>(.*?)</summary>", m.group(0), re.DOTALL)
        return summary_match.group(1).strip() if summary_match else ""

    return re.sub(r"<details>.*?</details>", replace_details, text, flags=re.DOTALL)
