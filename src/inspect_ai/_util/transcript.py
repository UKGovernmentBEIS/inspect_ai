import html
import re
from typing import Any

from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from inspect_ai._util.content import ContentReasoning

from .format import format_function_call


def transcript_code_theme() -> str:
    return "github-dark"


def transcript_markdown(content: str, *, escape: bool = False) -> Markdown:
    code_theme = transcript_code_theme()
    return Markdown(
        html_escape_markdown(content) if escape else content,
        code_theme=code_theme,
        inline_code_lexer="python",
        inline_code_theme=code_theme,
    )


def html_escape_markdown(content: str) -> str:
    """Escape markdown lines that aren't in a code block."""
    codeblock_pattern = re.compile("`{3,}")
    current_codeblock = ""
    escaped: list[str] = []
    lines = content.splitlines()
    for line in lines:
        # look for matching end of codeblock
        if current_codeblock:
            if current_codeblock in line:
                current_codeblock = ""
                escaped.append(line)
                continue

        # look for beginning of codeblock
        match = codeblock_pattern.search(line)
        if match:
            current_codeblock = match[0]
            escaped.append(line)
            continue

        # escape if we are not in a codeblock
        if current_codeblock:
            escaped.append(line)
        else:
            escaped.append(html.escape(line, quote=False))

    return "\n".join(escaped)


def set_transcript_markdown_options(markdown: Markdown) -> None:
    code_theme = transcript_code_theme()
    markdown.code_theme = code_theme
    markdown.inline_code_lexer = "python"
    markdown.inline_code_theme = code_theme


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
            set_transcript_markdown_options(c)

    return Panel(
        Group(*content),
        title=title,
        title_align=title_align,
        box=box,
        padding=padding,
        highlight=True,
        expand=True,
    )


def transcript_reasoning(reasoning: ContentReasoning) -> list[RenderableType]:
    content: list[RenderableType] = []
    text = (
        reasoning.reasoning
        if not reasoning.redacted
        else "Reasoning encrypted by model provider."
    ).strip()

    if len(text) > 0:
        content.append(
            transcript_markdown(
                f"**<think>**  \n{text}  \n**</think>**\n\n", escape=True
            )
        )
        content.append(Text())
    return content


def transcript_separator(
    title: str, color: str, characters: str = "─"
) -> RenderableType:
    return Rule(
        title=title,
        characters=characters,
        style=f"{color} bold",
        align="center",
        end="\n\n",
    )


def transcript_function(function: str, arguments: dict[str, Any]) -> RenderableType:
    call = format_function_call(function, arguments)
    return transcript_markdown("```python\n" + call + "\n```\n")


DOUBLE_LINE = Box(" ══ \n    \n    \n    \n    \n    \n    \n    \n")

LINE = Box(" ── \n    \n    \n    \n    \n    \n    \n    \n")

DOTTED = Box(" ·· \n    \n    \n    \n    \n    \n    \n    \n")

NOBORDER = Box("    \n    \n    \n    \n    \n    \n    \n    \n")
