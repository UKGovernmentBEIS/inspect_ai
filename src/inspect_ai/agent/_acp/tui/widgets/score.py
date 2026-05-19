"""Score widget — renders one inline :class:`ScoreChip`.

Mid-stream scoring chip (mockup 02e). Mounted into the transcript
alongside message groups and tool calls when an ``inspect/event``
notification for a ``ScoreEvent`` arrives during the post-agent
scoring window.

Composed as a controlled-content header (scorer / value / passed
status) plus an optional collapsible markdown body for the score
explanation. The split is deliberate: the header is the only thing
that goes through Rich's ``markup=True`` parser, and it only ever
splices in short, escaped tokens — so explanations containing source
snippets, diffs, brackets, backslashes, or any other parser-confusing
content can't take the transcript render down. The body renders via
:class:`CollapsibleContent` → :class:`StyledMarkdown`, which uses
Rich's Markdown parser (not its markup parser).
"""

from __future__ import annotations

from rich.markup import escape as escape_markup
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from ..state import ScoreChip
from ._collapsible import CollapsibleContent

_SCORE_REASON_MAX_LINES = 8
"""Per-chip cap before the ``… N more lines`` expander kicks in.

Score explanations are typically short — a sentence or two of
justification — but scorers that quote source / diffs / model output
in their rationale can run long. 8 lines keeps the resting transcript
scannable without losing the affordance to read the full text.
"""


class ScoreChipWidget(Widget):
    """Inline chip for a scoring outcome: header + optional markdown body."""

    DEFAULT_CSS = """
    ScoreChipWidget {
        height: auto;
        margin: 0 0 1 0;
    }
    ScoreChipWidget Static.chip {
        height: 1;
    }
    ScoreChipWidget .score-body {
        height: auto;
        padding: 0 0 0 2;
    }
    """

    def __init__(self, chip: ScoreChip) -> None:
        super().__init__()
        self._chip = chip

    def compose(self) -> ComposeResult:
        yield Static(self._chip_text(), classes="chip", markup=True)
        reason = self._reason_text()
        if reason is not None and not self._is_indicator():
            with Vertical(classes="score-body"):
                yield CollapsibleContent(reason, max_lines=_SCORE_REASON_MAX_LINES)

    def _reason_text(self) -> str | None:
        r"""The reason / explanation as plain text (no markup escaping).

        Returned verbatim — markdown rendering downstream is markup-
        parser-safe, so we don't need to neutralise ``[`` / ``\\``.
        Empty / whitespace-only reasons collapse to ``None`` so the
        body block isn't mounted with nothing to show.
        """
        if not self._chip.reason:
            return None
        text = self._chip.reason.strip()
        return text if text else None

    def _is_indicator(self) -> bool:
        """Chip with no scorer / value / passed but a reason.

        Used by the per-scorer ``scoring · X…`` progress markers
        mounted off ``span_begin`` events. Renders the reason inline
        in the chip line (no body, no ``score · `` prefix) — the
        prefix would otherwise read ``score · scoring · X…`` which
        is redundant.
        """
        return (
            self._chip.scorer is None
            and not self._chip.value
            and self._chip.passed is None
            and bool(self._reason_text())
        )

    def _chip_text(self) -> str:
        # The chip line is the ONLY place markup=True is used in this
        # widget — every spliced-in user value is run through
        # ``escape_markup`` so brackets / backslashes / ``[/]`` in
        # scorer names or value strings can't be misread as Rich
        # markup tags (which would raise ``MarkupError`` and take the
        # whole transcript render down with it).
        if self._is_indicator():
            reason = self._reason_text()
            assert reason is not None  # narrowed by _is_indicator
            # Collapse newlines for the single-line indicator render.
            return f"[$success]{escape_markup(reason.replace(chr(10), ' '))}[/]"

        parts: list[str] = ["[$success]score[/]"]
        if self._chip.scorer is not None:
            parts.append(f"[dim]·[/] [$success]{escape_markup(self._chip.scorer)}[/]")
        if self._chip.value:
            parts.append(
                f"[dim]·[/] value [$success]{escape_markup(self._chip.value)}[/]"
            )
        if self._chip.passed is True:
            parts.append("[dim]·[/] [$success]passed[/]")
        elif self._chip.passed is False:
            parts.append("[dim]·[/] [$warning]failed[/]")
        return " ".join(parts)
