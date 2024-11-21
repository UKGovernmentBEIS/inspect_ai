from rich.console import RenderableType
from rich.style import Style
from rich.text import Text


def lines_display(
    text: str, max_lines: int = 100, style: str | Style = ""
) -> list[RenderableType]:
    lines = text.splitlines()
    if len(lines) > max_lines:
        content: list[RenderableType] = [
            Text("\n".join(lines[0:max_lines]), style=style)
        ]
        content.append(Text())
        content.append(
            Text.from_markup(
                f"[italic]Output truncated ({len(lines) - max_lines} additional lines)...[/italic]",
                style=style,
            )
        )
    else:
        content = [Text(text, style=style)]

    return content
