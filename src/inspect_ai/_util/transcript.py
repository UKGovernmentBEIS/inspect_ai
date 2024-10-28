from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


def transcript_panel(
    title: str,
    subtitle: str | None = None,
    content: RenderableType | list[RenderableType] = [],
    level: int = 1,
) -> Panel:
    # handle title/level
    if level == 1:
        title = f"[bold][blue]{title}[/blue][/bold]"
        title_align: AlignMethod = "left"
        box = ROUNDED
    else:
        title = f"[bold]{title}[/bold]"
        title_align = "center"
        box = LINE

    # resolve content to list
    content = content if isinstance(content, list) else [content]

    # inject subtitle
    if subtitle:
        content.insert(0, Text())
        content.insert(0, Text.from_markup(f"[bold]{subtitle}[/bold]"))

    # use vs theme for markdown code
    for c in content:
        if isinstance(c, Markdown):
            c.code_theme = "xcode"

    return Panel(
        Group(*content),
        title=title,
        title_align=title_align,
        box=box,
        highlight=True,
        expand=True,
    )


LINE: Box = Box(" ── \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n")
