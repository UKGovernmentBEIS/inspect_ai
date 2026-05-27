"""Shared helpers for rendering message + tool-call content as Markdown.

Two pieces:

- :class:`StyledCodeBlock` — a ``rich.markdown.CodeBlock`` subclass
  that distinguishes language-tagged code from unlabelled output:
  fenced blocks with a language render as syntax-highlighted code on
  the standard Inspect dark background; fences with no language render
  as plain text (no chrome). Solves the "we can't tell command from
  output" problem in tool cards where agents emit a fenced bash block
  followed by plain stdout.

- :class:`StyledMarkdown` — a thin :class:`rich.markdown.Markdown`
  subclass that swaps the default ``fence`` / ``code_block`` renderers
  for :class:`StyledCodeBlock`. Use this anywhere we'd otherwise reach
  for ``rich.markdown.Markdown``.

The colour theme matches Inspect's existing transcript renderer
(``transcript_code_theme`` in :mod:`inspect_ai._util.transcript`) so
the TUI feels visually continuous with ``inspect view`` and the rich
terminal display.
"""

from __future__ import annotations

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import CodeBlock, Heading, Markdown
from rich.syntax import Syntax
from rich.text import Text

from inspect_ai._util.transcript import transcript_code_theme

_CODE_BG = "#282c34"
"""Background colour for syntax-highlighted blocks.

Matches the existing ``CustomCodeBlock`` in
:mod:`inspect_ai._display.core.rich` so a transcript line you see in
the rich terminal display reads the same colour in the TUI.
"""


class StyledCodeBlock(CodeBlock):
    """Code block that styles labelled fences and leaves unlabelled fences plain.

    Inspect's tool cards typically emit one labelled fence (the
    command, e.g. ``bash``) followed by an unlabelled or output block
    (the stdout). Treating the two visually differently lets the eye
    separate "what was asked" from "what came back" without adding
    panel borders that bloat vertical space.
    """

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        code = str(self.text).rstrip()
        lexer = (self.lexer_name or "").strip().lower()
        # ``text`` is what markdown defaults to for an unlabelled
        # fence; treat both that and the empty case as "no language".
        if lexer and lexer != "text":
            yield Syntax(
                code,
                lexer,
                theme=transcript_code_theme(),
                word_wrap=True,
                background_color=_CODE_BG,
                # One cell of padding on every side so the code sits
                # comfortably inside the dark background instead of
                # going flush to any edge.
                padding=1,
            )
        else:
            # No language → just text. No background, no syntax pass —
            # this is typically tool stdout where syntax highlighting
            # would be wrong anyway.
            yield Text(code)


class PlainHeading(Heading):
    """Headings rendered as plain bold text, left-aligned.

    Rich's default applies the panel/underline + centred-h1 treatment
    via theme styles; both feel heavyweight in a chat transcript and
    introduce the pink underline the operator complained about. This
    variant strips the inherited style and just bolds the text — the
    structure is still clear without imposing decorative chrome.
    """

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        text = self.text.copy()
        text.justify = "left"
        text.stylize("bold")
        # Override the theme's `markdown.h1` / `h2` etc. style so the
        # default underline / panel doesn't reapply on top of ours.
        text.style = "bold"
        yield text


class StyledMarkdown(Markdown):
    """Markdown variant with custom code + heading renderers."""

    elements = {
        **Markdown.elements,
        "fence": StyledCodeBlock,
        "code_block": StyledCodeBlock,
        "heading_open": PlainHeading,
    }
