from rich.console import RenderableType
from rich.style import Style
from rich.text import Text

from inspect_ai._util.text import truncate_lines


def lines_display(
    text: str, max_lines: int = 100, style: str | Style = ""
) -> list[RenderableType]:
    lines, truncated = truncate_lines(text, max_lines)

    content: list[RenderableType] = [Text(lines, style=style)]
    if truncated is not None:
        content.append(Text())
        content.append(
            Text.from_markup(
                f"[italic]Output truncated ({truncated} additional lines)...[/italic]",
                style=style,
            )
        )

    return content
