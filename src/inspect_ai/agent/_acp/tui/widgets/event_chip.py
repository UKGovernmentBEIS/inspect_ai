"""Event-chip widget — renders one inline :class:`EventChip`.

Mid-stream inline rendering of Inspect-native transcript events
(``SampleLimitEvent``, ``ErrorEvent``, ``CompactionEvent``,
``InfoEvent``) as colored cards that sit alongside message groups and
tool-call cards. Mounted from the ``inspect/event`` raw firehose;
see :meth:`SessionState.consume_inspect_event` for the producer side.

Each event kind gets its own glyph + colour + background tint via a
per-kind table — that's all the per-kind logic the widget carries.
The header text and body are already formatted into compact strings
by the state-layer builders, so the widget is dumb: render the chip
row, mount the optional collapsible body, and (for ``error``) mount
the click-to-expand traceback block.

Composed as a controlled-content header (markup=True, escaped) plus
an optional ``CollapsibleContent``-wrapped markdown body — the same
split :class:`ScoreChipWidget` uses, for the same reason: the header
is the only place markup=True is in play, and only short escaped
tokens get spliced in, so a body containing brackets / backslashes /
tracebacks can't take the transcript render down.
"""

from __future__ import annotations

from typing import NamedTuple

from rich.json import JSON as RichJSON
from rich.markup import escape as escape_markup
from rich.style import Style
from rich.text import Span as RichSpan
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from ..state import EventChip, EventChipKind
from ._collapsible import CollapsibleContent
from ._scroll import schedule_scroll_to_end_if_at_bottom

_EVENT_BODY_MAX_LINES = 8
"""Per-chip cap before the ``… N more lines`` expander kicks in.

Same value :class:`ScoreChipWidget` uses — keeps the resting
transcript scannable while letting operators expand on demand.
Tracebacks ride a separate click-to-expand affordance below the body
(see :class:`_TracebackBlock`) so the body cap doesn't have to
accommodate them.
"""


class _Style(NamedTuple):
    """Per-kind visual style for an event chip."""

    glyph: str
    """Leading single-character marker rendered in the kind's colour."""

    colour: str
    """Hex literal for the glyph and the bolded event-word in the
    header. Drawn from the same Tokyo-Night-family palette as
    :data:`message._PALETTE` (rather than ``$warning`` / ``$error``
    / ``$accent`` theme tokens) so the chip's accent reads
    distinctly on the default theme — the tokens resolve to muted
    shades that disappear against the transcript body."""

    css_class: str
    """CSS class appended to the widget root so the per-kind
    background tint rule in :attr:`EventChipWidget.DEFAULT_CSS` can
    target this kind."""

    event_word: str
    """The text that follows the glyph in the header. Renders bold
    and coloured so the operator's eye lands on the kind first; the
    rest of the header summary is built by the state-layer with
    ``·``-separated details and renders in the default text colour
    (no accent bleed)."""


# Hex palette — see ``message._PALETTE`` for the convention. Bright
# enough to read against the transcript on the default Tokyo Night
# theme; chosen per-kind so each event family has a distinct accent
# without relying on theme-token resolution.
_AMBER = "#e0af68"
_RED = "#f7768e"
_CYAN = "#7dcfff"
# Manila-ish yellow for info events. Distinct from the amber warning
# (sample_limit) so the two yellows don't read as the same chip
# family, and distinct from cyan (compaction) so info events stop
# looking like compactions. Matches the system-message yellow in
# ``message._PALETTE`` because info events and system messages share
# the same "subsystem-spoke-up" semantic.
_YELLOW = "#e6dc7a"


_STYLES: dict[EventChipKind, _Style] = {
    "sample_limit": _Style(
        glyph="⚠", colour=_AMBER, css_class="kind-warning", event_word="limit"
    ),
    "error": _Style(glyph="✗", colour=_RED, css_class="kind-error", event_word="error"),
    "compaction": _Style(
        glyph="↺", colour=_CYAN, css_class="kind-accent", event_word="compaction"
    ),
    "info": _Style(glyph="ⓘ", colour=_YELLOW, css_class="kind-info", event_word="info"),
}


class EventChipWidget(Widget):
    """Inline chip for an Inspect-native transcript event."""

    DEFAULT_CSS = """
    /* ``padding: 0 2`` + ``.event-body { padding-left: 2 }`` matches
     * :class:`MessageWidget` exactly so the event chip's glyph sits
     * in the same column as the assistant / user bullets and its
     * body indents in the same column as the message body text. */
    EventChipWidget {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
    }
    EventChipWidget Static.chip {
        height: 1;
    }
    EventChipWidget .event-body {
        height: auto;
        padding-left: 2;
    }
    EventChipWidget .event-body-plain {
        height: auto;
    }
    /* Per-kind background tint. Subtle full-card band so the chip
     * reads as a meta event (system signal) rather than as
     * conversation content — message and tool cards have no tint.
     * 12% gives the band enough presence to register without
     * competing with the chip's text. */
    EventChipWidget.kind-warning { background: #e0af68 12%; }
    EventChipWidget.kind-error { background: #f7768e 12%; }
    EventChipWidget.kind-accent { background: #7dcfff 12%; }
    EventChipWidget.kind-info { background: #e6dc7a 12%; }
    """

    def __init__(self, chip: EventChip) -> None:
        super().__init__()
        self._chip = chip
        style = _STYLES[chip.kind]
        self.add_class(style.css_class)

    def compose(self) -> ComposeResult:
        yield Static(self._chip_text(), classes="chip", markup=True)
        # Body — text + optional traceback link. Only mount the
        # container when at least one of the two will have content;
        # otherwise the empty Vertical eats a row of whitespace under
        # a header-only chip and breaks the tight stack you'd expect.
        body = self._body_text()
        has_traceback = bool(self._chip.traceback)
        if body is None and not has_traceback:
            return
        with Vertical(classes="event-body"):
            if body is not None:
                if self._chip.body_format == "json":
                    # JSON has its own collapsible wrapper because we
                    # can't reuse ``CollapsibleContent`` — that one re-
                    # wraps through ``StyledMarkdown`` (so it can show
                    # the truncation note), which would re-introduce
                    # the dark code-block band over the chip's tint.
                    # ``_CollapsibleJSON`` renders via ``_render_json``
                    # directly to preserve the transparent background,
                    # caps at the shared ``_EVENT_BODY_MAX_LINES`` so
                    # the resting transcript reads consistently with
                    # the markdown body path, and toggles two-way like
                    # ``_TracebackBlock`` does.
                    yield _CollapsibleJSON(body, max_lines=_EVENT_BODY_MAX_LINES)
                elif self._chip.body_format == "plain":
                    # Plain text — used for error messages. Skip
                    # ``CollapsibleContent`` / ``StyledMarkdown`` so
                    # the body sits flush against the chip header
                    # (Rich Markdown's block-spacing model introduces
                    # a leading blank row that reads as wrong inside
                    # a one-line chip). Error messages are typically
                    # short; if they grow long, the traceback block
                    # below carries the deep-dive content.
                    yield Static(body, classes="event-body-plain", markup=False)
                else:
                    yield CollapsibleContent(body, max_lines=_EVENT_BODY_MAX_LINES)
            if has_traceback:
                yield _TracebackBlock(self._chip.traceback or "")

    def _body_text(self) -> str | None:
        if not self._chip.body_text:
            return None
        text = self._chip.body_text.strip()
        return text if text else None

    def _chip_text(self) -> str:
        # The chip line is the ONLY place markup=True is used in this
        # widget — every spliced-in user value (header summary built
        # by the state layer from event fields like error messages
        # and limit types) is escaped so brackets / backslashes in
        # those values can't be misread as Rich markup tags.
        style = _STYLES[self._chip.kind]
        glyph = f"[{style.colour}]{style.glyph}[/]"
        # Event word is BOLD + coloured (matches the message
        # convention — ``[bold {fg}]role[/]`` in ``message.py``).
        # Bolding helps the kind read first against the tinted band.
        event_word = f"[bold {style.colour}]{style.event_word}[/]"
        # The state-layer builds ``header_summary`` as
        # ``"<event_word> · …"`` for the common case. Split on the
        # first ``·`` so we can colour the event word and render the
        # remainder dim with dim separators — mirrors the score
        # chip's visual vocabulary ("header pops, details whisper").
        # If the summary has no ``·`` (e.g. just ``"error"``) we
        # render the bare event word.
        summary = self._chip.header_summary
        if " · " in summary:
            _, _, rest = summary.partition(" · ")
            rest_segments = rest.split(" · ")
            tail = " ".join(
                f"[dim]·[/] [dim]{escape_markup(seg)}[/]"
                for seg in rest_segments
                if seg
            )
            return f"{glyph} {event_word} {tail}".rstrip()
        return f"{glyph} {event_word}"


def _render_json(body: str) -> RichJSON:
    """Build a :class:`rich.json.JSON` with un-bolded keys.

    Rich's default ``json.key`` theme style is bold + blue — the bold
    makes keys outshout the rest of the body inside the info card,
    which competes with the chip's own header for visual weight. Layer
    an explicit ``Style(bold=False)`` span over each key range so the
    theme colour from the original ``json.key`` span still flows
    through but the bold flag is overridden. Cheaper than swapping
    the highlighter or building a custom Console theme, and survives
    Rich tweaking the resolved colour for ``json.key`` in the future.
    """
    rendered = RichJSON(body)
    rendered.text.spans.extend(
        RichSpan(s.start, s.end, Style(bold=False))
        for s in list(rendered.text.spans)
        if s.style == "json.key"
    )
    return rendered


class _CollapsibleJSON(Widget):
    """Capped JSON body for :class:`InfoEvent` chips with click-to-toggle.

    JSON-specific sibling to :class:`CollapsibleContent`: same vocab
    (a ``… N more lines`` italic-underline-muted clickable note when
    truncated), but renders via :func:`_render_json` instead of
    ``StyledMarkdown`` so the chip's tinted info band shows through
    cleanly — ``StyledMarkdown`` would re-wrap the JSON in a fenced
    code block and stamp a dark rectangle over the tint.

    Toggles two-way (click expands; click again collapses), matching
    :class:`_TracebackBlock` and ``_ReasoningBlock`` — operators
    scanning a long JSON payload should be able to put it back in
    the box once they've seen what they need.

    Without this cap an InfoEvent carrying a large dict/list payload
    could dump an unbounded JSON tree into the transcript and make
    the TUI hard to scroll past.
    """

    DEFAULT_CSS = """
    _CollapsibleJSON { height: auto; }
    _CollapsibleJSON .json-body { height: auto; }
    /* Truncation note mirrors ``CollapsibleContent.truncation-note``
     * and ``_TracebackBlock.traceback-link``: italic + underline +
     * muted to read as clickable; accent on hover. Consistent
     * affordance across every collapsible block in the transcript. */
    _CollapsibleJSON .json-note {
        color: $text-muted;
        text-style: italic underline;
        height: auto;
    }
    _CollapsibleJSON .json-note:hover { color: $accent; }
    """

    def __init__(self, body: str, *, max_lines: int) -> None:
        super().__init__()
        self._body = body
        self._max_lines = max_lines
        self._expanded = False
        # Render once so the click handler doesn't have to re-parse.
        # Slice by lines on the rendered ``Text`` so the truncated
        # view keeps the un-bolded key spans + JSON colouring intact.
        self._full_text = _render_json(body).text
        self._lines = self._full_text.split("\n")
        self._omitted = max(0, len(self._lines) - max_lines)

    def compose(self) -> ComposeResult:
        yield Static(self._visible_text(), classes="json-body", id="json-body")
        if self._omitted > 0:
            yield Static(
                self._note_label(),
                classes="json-note",
                id="json-note",
                markup=False,
            )

    def _visible_text(self) -> Text:
        if self._expanded or self._omitted == 0:
            return self._full_text
        return Text("\n").join(self._lines[: self._max_lines])

    def _note_label(self) -> str:
        if self._expanded:
            return "… collapse"
        plural = "s" if self._omitted != 1 else ""
        return f"… {self._omitted} more line{plural}"

    def on_click(self) -> None:
        # No-op when the body fits — no note was mounted, so a click
        # on the body shouldn't toggle anything (we'd be hiding the
        # full text the operator can already see).
        if self._omitted == 0:
            return
        self._expanded = not self._expanded
        try:
            body = self.query_one("#json-body", Static)
        except NoMatches:
            return
        body.update(self._visible_text())
        try:
            note = self.query_one("#json-note", Static)
        except NoMatches:
            return
        note.update(self._note_label())
        schedule_scroll_to_end_if_at_bottom(self)


class _TracebackBlock(Widget):
    """Click-to-toggle traceback block for an error event.

    Default state shows ONLY the word ``traceback`` rendered with the
    same italic + underline + muted treatment ``_ReasoningBlock`` and
    ``CollapsibleContent`` use for their click affordances — so the
    operator reads it as clickable without a fresh visual vocabulary
    to learn. Click anywhere on the block to expand the body in
    place; click again to collapse it back.

    Tracebacks are typically high-detail but rarely the first thing
    the operator wants to see; keeping the resting chip uncluttered
    and gating expansion on a click matches how reasoning blocks
    handle the same "useful when needed, noisy by default" tension.
    """

    DEFAULT_CSS = """
    _TracebackBlock { height: auto; margin-top: 1; }
    _TracebackBlock.collapsed { margin-top: 0; }
    _TracebackBlock:last-child { margin-bottom: 0; }
    /* Link styling mirrors CollapsibleContent's .truncation-note and
     * _ReasoningBlock's .reasoning-link so the affordance reads
     * consistently across the transcript: italic + underline + muted,
     * with an accent hover tint. */
    _TracebackBlock .traceback-link {
        color: $text-muted;
        text-style: italic underline;
        height: auto;
    }
    _TracebackBlock .traceback-link:hover { color: $accent; }
    _TracebackBlock .traceback-body {
        color: $text-muted;
        height: auto;
    }
    /* Body hidden until the click expands. Toggled by removing the
     * ``collapsed`` class in ``on_click``. */
    _TracebackBlock.collapsed .traceback-body { display: none; }
    """

    def __init__(self, traceback: str) -> None:
        super().__init__()
        self._traceback = traceback
        # Start collapsed — only the "traceback" link is visible.
        self.add_class("collapsed")

    def compose(self) -> ComposeResult:
        yield Static("traceback", classes="traceback-link")
        # The state layer prefers ``error.traceback_ansi`` over the
        # plain ``traceback`` field — upstream ``format_traceback``
        # bakes the full ``rich.traceback.Traceback`` output (frame
        # summaries + syntax-highlighted source-line context) into
        # ANSI escape codes, so parsing them back with ``Text.from_ansi``
        # gives us the same styled rendering Inspect's own console
        # display produces. ``Text`` carries only foreground styles
        # from the ANSI codes, so the chip's tinted error band shows
        # through cleanly. If the wire only had the plain traceback
        # (no escape codes), ``from_ansi`` still produces a readable
        # ``Text`` — just without colour.
        yield Static(Text.from_ansi(self._traceback), classes="traceback-body")

    def on_click(self) -> None:
        # Toggle — click expands when collapsed, collapses when
        # expanded. Diverges from CollapsibleContent (which is
        # one-way) for the same reason _ReasoningBlock does:
        # tracebacks are scannable rather than something you copy
        # out, so making the operator rescroll to hide them again
        # would be friction.
        self.toggle_class("collapsed")
        # Auto-scroll if the operator was at the bottom — expanded
        # tracebacks can run dozens of rows; without this they'd be
        # hidden below the fold on the chip they just clicked.
        schedule_scroll_to_end_if_at_bottom(self)

    def set_traceback(self, traceback: str) -> None:
        """Replace the traceback body in place.

        Reserved for future "in-flight error update" flows that don't
        exist today — every ErrorEvent is terminal, so the chip's
        traceback is set once at mount and never mutates. The setter
        is here as a forward-compat sibling to ``_ReasoningBlock.set_text``;
        callers should otherwise rebuild the widget via the standard
        transcript re-mount path.
        """
        self._traceback = traceback
        try:
            body = self.query_one(".traceback-body", Static)
        except NoMatches:
            return
        body.update(Text.from_ansi(self._traceback))
