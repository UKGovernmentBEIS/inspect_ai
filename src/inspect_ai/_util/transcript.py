from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from rich.align import AlignMethod
from rich.box import ROUNDED, Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

if TYPE_CHECKING:
    from rich.markdown import Markdown

from inspect_ai._util.content import ContentReasoning
from inspect_ai._util.text import truncate_lines

from .format import format_function_call


def transcript_code_theme() -> str:
    return "github-dark"


def transcript_markdown(content: str, *, escape: bool = False) -> Markdown:
    from rich.markdown import Markdown

    code_theme = transcript_code_theme()
    return Markdown(
        html_escape_markdown(content) if escape else content,
        code_theme=code_theme,
        inline_code_lexer="python",
        inline_code_theme=code_theme,
    )


def html_escape_markdown(content: str) -> str:
    """Escape markdown lines that aren't in a code block.

    Which lines count as "in a code block" is decided by the same CommonMark
    tokenizer that rich uses to render the markdown, not by tracking fences
    by hand. Hand-rolled fence tracking kept missing edge cases (fences
    nested in list items, "closing" fences carrying an info string, fences
    indented four or more spaces), and every miss re-opens the unescaped-HTML
    hole this function exists to close.
    """
    from markdown_it import MarkdownIt

    code_lines: set[int] = set()
    for token in MarkdownIt("commonmark").parse(content):
        if token.type in ("fence", "code_block") and token.map:
            code_lines.update(range(token.map[0], token.map[1]))

    return "\n".join(
        line if i in code_lines else html.escape(line, quote=False)
        for i, line in enumerate(content.splitlines())
    )


def set_transcript_markdown_options(markdown: Markdown) -> None:
    code_theme = transcript_code_theme()
    markdown.code_theme = code_theme
    markdown.inline_code_lexer = "python"
    markdown.inline_code_theme = code_theme


def transcript_panel(
    title: str,
    subtitle: str | None = None,
    content: RenderableType | list[RenderableType] | None = None,
    level: int = 1,
) -> Panel:
    from rich.markdown import Markdown

    # resolve content to list
    if content is None:
        content = []
    elif not isinstance(content, list):
        content = [content]

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


def content_display(text: str, max_lines: int = 50) -> list[RenderableType]:
    """Truncate text content and render as markdown."""
    truncated_text, additional = truncate_lines(text, max_lines)
    content: list[RenderableType] = [transcript_markdown(truncated_text, escape=True)]
    if additional is not None:
        content.append(Text())
        content.append(
            Text.from_markup(
                f"[italic]Content truncated ({additional} additional lines)...[/italic]"
            )
        )
    return content


def transcript_reasoning(reasoning: ContentReasoning) -> list[RenderableType]:
    content: list[RenderableType] = []
    text = (
        (reasoning.reasoning or reasoning.summary or "")
        if not reasoning.redacted
        else (reasoning.summary or "Reasoning encrypted by model provider.")
    ).strip()

    if len(text) > 0:
        truncated_text, additional = truncate_lines(text, 50)
        if additional is not None:
            truncated_text += (
                f"\n\n_Content truncated ({additional} additional lines)..._"
            )
        content.append(
            transcript_markdown(
                f"**<think>**  \n{truncated_text}  \n**</think>**\n\n", escape=True
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
