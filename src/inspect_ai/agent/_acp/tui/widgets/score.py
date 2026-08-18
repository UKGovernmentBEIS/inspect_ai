"""Score widget — renders one inline :class:`ScoreChip`.

Mid-stream scoring chip (mockup 02e). Mounted into the transcript
alongside message groups, tool calls, and other event chips when an
``inspect/event`` notification for a ``ScoreEvent`` arrives during the
post-agent scoring window.

Composed as a controlled-content header (scorer / value / passed
status) plus an optional body that splits the answer (always
visible) from the explanation (mounted behind a click-to-expand
``explanation`` link mirroring :class:`_ReasoningBlock` and
:class:`_TracebackBlock`). The header is the only thing that goes
through Rich's ``markup=True`` parser, and it only ever splices in
short, escaped tokens — so explanations containing source snippets,
diffs, brackets, backslashes, or any other parser-confusing content
can't take the transcript render down. The explanation body renders
via :class:`StyledMarkdown` (Rich's Markdown parser, not its markup
parser) inside the collapsible block.

Shares the leading-glyph + tinted-background visual treatment with
:class:`EventChipWidget` so all transcript-event cards read as a
family (mockup ``events.png``). Indicator-mode chips (the per-scorer
``scoring · X…`` placeholders mounted off ``span_begin``) keep their
existing pared-down rendering — no glyph, no background tint, no
body — so the placeholder stays visually distinct from the real
score chip that supersedes it.
"""

from __future__ import annotations

import time

from rich.markup import escape as escape_markup
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from ..state import ScoreChip
from ._collapsible import CollapsibleContent
from ._formatting import SPINNER_FRAMES, format_duration
from ._scroll import schedule_scroll_to_end_if_at_bottom
from .markdown import StyledMarkdown

_ANSWER_MAX_LINES = 6
"""Per-chip cap on the answer body before the ``… N more lines`` expander kicks in.

Most scorer answers are short (a single line or a sentence), but
some carry the full model completion — code blocks, multi-paragraph
prose, etc. 6 lines fits a typical small-function code block plus a
sentence of framing without scrolling the resting transcript; longer
answers gain the standard one-way expand affordance shared with
tool-call bodies and assistant message bodies.
"""

# Single accent colour for all score chips. We dropped the green
# "definitive pass" variant because tinting only when ``value == 1.0``
# implies a binary verdict the score event itself doesn't carry —
# many real scorers emit continuous values where 0.7 isn't a "fail"
# and 1.0 isn't necessarily a "success" (rubric-dependent). Painting
# everything purple removes that false verdict signal and lets the
# value text carry the actual meaning.
#
# Purple specifically (not cyan): cyan ``#7dcfff`` sits too close to
# the assistant role's ``#7aa2f7`` blue and reads as the same
# chip-family at a glance. Purple lifts the score chip off the blue
# axis entirely so the operator can scan score chips apart from
# in-flight assistant turns. It collides with the operator-injection
# marker's purple (also ``#bb9af7``), but those appear in different
# transcript contexts (mid-turn user injection vs. post-agent scoring
# phase) — they don't compete for the same eye target.
_PURPLE = "#bb9af7"
_SCORE_GLYPH = "★"


class ScoreChipWidget(Widget):
    """Inline chip for a scoring outcome: header + optional markdown body."""

    DEFAULT_CSS = """
    /* ``padding: 0 2`` + ``.score-body { padding-left: 2 }`` matches
     * :class:`MessageWidget` exactly so the score chip's glyph sits
     * in the same column as the assistant / user bullets and its
     * body indents in the same column as the message body text. */
    ScoreChipWidget {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
    }
    ScoreChipWidget Static.chip {
        height: 1;
    }
    ScoreChipWidget .score-body {
        height: auto;
        padding-left: 2;
    }
    /* Explicit 1-row spacer between the answer body and the
     * explanation block, mounted only when the answer is multi-line.
     * A real widget (not a margin) so Textual reflows on click-to-
     * expand can't flatten it — every collapse / expand sequence
     * leaves the spacer intact, keeping the two affordances visually
     * separated. */
    ScoreChipWidget .answer-explanation-gap { height: 1; }
    /* Real score chips get a subtle purple card band (matches
     * EventChipWidget's per-kind tinting), so the operator's eye
     * reads "score landed" at a glance. Single tint regardless of
     * value — no green ``passed`` variant — so the chip doesn't
     * imply a verdict the score itself doesn't carry. Indicator-
     * mode chips (per-scorer ``scoring · X…`` placeholders) are
     * stripped of the tint and padding so the placeholder stays
     * visually quiet — it's a "still working" signal, not a result. */
    ScoreChipWidget.neutral { background: #bb9af7 8%; }
    ScoreChipWidget.indicator { padding: 0 2; background: transparent; }
    """

    def __init__(self, chip: ScoreChip) -> None:
        super().__init__()
        self._chip = chip
        # Spinner frame for the in-flight indicator chip. Same braille
        # animation the assistant + tool-call chips use, advanced by the
        # transcript's periodic tick via :meth:`tick_spinner`. Real
        # (terminal) score chips ignore the frame counter — there's
        # nothing to animate once a value has landed.
        self._spinner_frame = 0
        if self._is_indicator():
            self.add_class("indicator")
        else:
            # Every real score chip — passed, failed, partial, non-
            # binary — gets the same purple ``neutral`` treatment. We
            # used to split passed=True off into a green ``passed``
            # tint, but that promoted a binary verdict onto continuous
            # scores where it didn't apply; the chip now just signals
            # "score landed" and the value text carries the meaning.
            self.add_class("neutral")

    def compose(self) -> ComposeResult:
        yield Static(self._chip_text(), classes="chip", markup=True)
        if self._is_indicator():
            return
        answer = self._chip.answer.strip() if self._chip.answer else ""
        reason = self._chip.reason.strip() if self._chip.reason else ""
        if not answer and not reason:
            return
        with Vertical(classes="score-body"):
            if answer:
                # ``answer: <a>`` rides through the standard
                # :class:`CollapsibleContent` truncation pipeline —
                # short answers fit in the resting view, longer ones
                # get the shared ``… N more lines`` expand affordance.
                yield CollapsibleContent(
                    f"answer: {answer}", max_lines=_ANSWER_MAX_LINES
                )
            if reason:
                # When the answer above is multi-line (or truncated —
                # both have newlines in the source), insert an explicit
                # 1-row spacer between the answer and the explanation
                # block. We previously used ``margin-top`` on the
                # explanation block, but Textual would drop the margin
                # after the operator clicked to expand either side, so
                # the two cards ended up reading flush against each
                # other. An explicit spacer Static can't be flattened
                # by a reflow — it's a real widget with ``height: 1``.
                if answer and "\n" in answer:
                    yield Static("", classes="answer-explanation-gap")
                # Explanation rides behind a click-to-expand block —
                # scorer rationales can run long (rubric quotes, diffs,
                # model output) and the resting transcript stays
                # scannable when only the affordance is visible.
                yield _ExplanationBlock(reason)

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
            and bool(self._chip.reason and self._chip.reason.strip())
        )

    def _chip_text(self) -> str:
        # The chip line is the ONLY place markup=True is used in this
        # widget — every spliced-in user value is run through
        # ``escape_markup`` so brackets / backslashes / ``[/]`` in
        # scorer names or value strings can't be misread as Rich
        # markup tags (which would raise ``MarkupError`` and take the
        # whole transcript render down with it).
        if self._is_indicator():
            return self._indicator_text()

        # Same ``★`` glyph in every case — the icon is about "this
        # is a score", not a pass/fail verdict. Always purple too —
        # see the ``_PURPLE`` constant's docstring for why we dropped
        # the green ``passed`` variant.
        glyph_colour = _PURPLE
        # The event-word follows the message convention — coloured +
        # bold so the speaker (here, the scoring subsystem) reads
        # first against the band. Everything after the event word
        # (scorer name, ``value:`` label, the value itself) renders
        # dim — the bold coloured glyph + ``score`` word carry the
        # signal, so the trailing context shouldn't compete for the
        # eye. Matches the "header pops, details whisper" rhythm
        # used by other transcript-event chips.
        parts: list[str] = [
            f"[{glyph_colour}]{_SCORE_GLYPH}[/] [bold {glyph_colour}]score[/]"
        ]
        if self._chip.scorer is not None:
            parts.append(f"[dim]·[/] [dim]{escape_markup(self._chip.scorer)}[/]")
        if self._chip.value:
            parts.append(
                f"[dim]·[/] [dim]value:[/] [dim]{escape_markup(self._chip.value)}[/]"
            )
        return " ".join(parts)

    def _indicator_text(self) -> str:
        """Render the in-flight ``scoring · X · 12s`` chip line.

        Same shape as the terminal score chip — bold ``score`` event
        word, dim trailing context — but with a braille spinner in
        place of the ``★`` glyph and the elapsed timer in place of
        the ``value:`` slot. The spinner / colour pair mirrors what
        the assistant chip does while a model event is in flight
        (see :class:`MessageWidget._chip_text`), so the operator
        reads "this is the same kind of live signal" without a fresh
        visual vocabulary. Colour stays purple to keep the chip
        consistent with the neutral score it'll become once the
        scorer lands a value.
        """
        glyph = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
        parts: list[str] = [
            f"[{_PURPLE}]{glyph}[/] [bold {_PURPLE}]score[/]",
        ]
        scorer_name = self._chip.scorer_name
        if scorer_name:
            parts.append(f"[dim]·[/] [dim]{escape_markup(scorer_name)}[/]")
        elapsed = self._elapsed_str()
        if elapsed:
            parts.append(f"[dim]·[/] [dim]{elapsed}[/]")
        return " ".join(parts)

    def _elapsed_str(self) -> str:
        """Format the indicator's elapsed time as ``Ns`` / ``Nm Ns``.

        Reads ``time.monotonic()`` directly (rather than threading the
        session-state clock through to the widget) — clock injection
        is a state-layer concern and the widget is far enough downstream
        that a real ``monotonic`` reading is fine. Returns empty when
        the chip carries no ``started_at`` (defensive — indicators set
        it at mount, so this only short-circuits the rare path where a
        non-indicator chip ends up here).
        """
        if self._chip.started_at is None:
            return ""
        return format_duration(time.monotonic() - self._chip.started_at)

    def tick_spinner(self) -> None:
        """Advance the spinner / elapsed timer and re-render the chip.

        Called from the transcript's periodic tick — same dispatch
        path :class:`MessageWidget.tick_spinner` and
        :meth:`ToolCallWidget.tick_duration` use. No-op on terminal
        score chips (no spinner to animate; the timer would be a lie
        on a chip that's already done).
        """
        if not self._is_indicator():
            return
        self._spinner_frame += 1
        self._refresh_chip()

    def _refresh_chip(self) -> None:
        try:
            self.query_one(".chip", Static).update(self._chip_text())
        except NoMatches:
            pass


class _ExplanationBlock(Widget):
    """Click-to-toggle explanation block for a score's reason.

    Default state shows ONLY the word ``explanation`` rendered with
    the same italic + underline + muted treatment
    :class:`_ReasoningBlock` (``widgets/message.py``) and
    :class:`_TracebackBlock` (``widgets/event_chip.py``) use for
    their click affordances — so the operator reads it as clickable
    without a fresh visual vocabulary to learn. Click anywhere on
    the block to expand the body in place; click again to collapse
    it back.

    Scorer rationales are typically high-detail (rubric quotes,
    diffs, model output) but rarely the first thing the operator
    wants to see; keeping the resting chip uncluttered and gating
    expansion on a click matches the reasoning / traceback affordance
    elsewhere in the transcript.
    """

    DEFAULT_CSS = """
    _ExplanationBlock { height: auto; margin-top: 1; }
    _ExplanationBlock.collapsed { margin-top: 0; }
    _ExplanationBlock:last-child { margin-bottom: 0; }
    /* Link styling mirrors CollapsibleContent's .truncation-note and
     * the reasoning / traceback links so the affordance reads
     * consistently across the transcript: italic + underline +
     * muted, with an accent hover tint. */
    _ExplanationBlock .explanation-link {
        color: $text-muted;
        text-style: italic underline;
        height: auto;
    }
    _ExplanationBlock .explanation-link:hover { color: $accent; }
    _ExplanationBlock .explanation-body {
        color: $text-muted;
        height: auto;
    }
    /* Body hidden until the click expands. Toggled by removing the
     * ``collapsed`` class in ``on_click``. */
    _ExplanationBlock.collapsed .explanation-body { display: none; }
    """

    def __init__(self, explanation: str) -> None:
        super().__init__()
        self._explanation = explanation
        # Start collapsed — only the "explanation" link is visible.
        self.add_class("collapsed")

    def compose(self) -> ComposeResult:
        yield Static("explanation", classes="explanation-link")
        yield Static(StyledMarkdown(self._explanation), classes="explanation-body")

    def on_click(self) -> None:
        # Two-way toggle — same UX as reasoning/traceback. Explanation
        # bodies are scannable rather than something you copy out, so
        # making the operator rescroll to hide them would be friction.
        self.toggle_class("collapsed")
        # Auto-scroll if the operator was at the bottom — expanding
        # extends the chip past the previous bottom, and without this
        # they'd be left looking at the same frame with the new body
        # hidden below the fold.
        schedule_scroll_to_end_if_at_bottom(self)

    def set_explanation(self, explanation: str) -> None:
        """Replace the explanation body in place.

        Forward-compat sibling to :meth:`_ReasoningBlock.set_text` /
        :meth:`_TracebackBlock.set_traceback`. Today every ScoreEvent
        is terminal — the chip's explanation is set once at mount and
        never mutates — so this is reserved for future in-flight
        update flows that don't yet exist. Callers should otherwise
        rebuild the widget via the standard transcript re-mount path.
        """
        self._explanation = explanation
        try:
            body = self.query_one(".explanation-body", Static)
        except NoMatches:
            return
        body.update(StyledMarkdown(self._explanation))
