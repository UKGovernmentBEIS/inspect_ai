from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

MARKDOWN_CODE_THEME = "xcode"


def transcript_markdown(content: str) -> Markdown:
    return Markdown(content, code_theme=MARKDOWN_CODE_THEME)


def transcript_panel(
    title: str,
    subtitle: str | None = None,
    content: RenderableType | list[RenderableType] = [],
    level: int = 1,
) -> Panel:
    # resolve content to list
    content = content if isinstance(content, list) else [content]

    # no padding if there is no content
    padding = (0, 1) if content else (0, 0)

    # handle title/level
    if level == 1:
        title = f"[bold][blue]{title}[/blue][/bold]"
        title_align: AlignMethod = "left"
        # box if content, else line
        box = ROUNDED if content else LINE
    else:
        title = f"[bold]{title}[/bold]"
        title_align = "center"
        if level == 2:
            box = LINE
        else:
            box = DOTTED

    # inject subtitle
    if subtitle:
        content.insert(0, Text())
        content.insert(0, Text.from_markup(f"[bold]{subtitle}[/bold]"))

    # use xcode theme for markdown code
    for c in content:
        if isinstance(c, Markdown):
            c.code_theme = MARKDOWN_CODE_THEME

    return Panel(
        Group(*content),
        title=title,
        title_align=title_align,
        box=box,
        padding=padding,
        highlight=True,
        expand=True,
    )


LINE = Box(" ── \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n")

DOTTED = Box(" ·· \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n" "    \n")
