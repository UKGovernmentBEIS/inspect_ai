"""Phase 7 widget pilot tests: ``EventChipWidget`` rendering.

Mounts a single :class:`EventChipWidget` per test inside a one-shot
Textual app and asserts the chip renders the expected glyph + header
text, the per-kind CSS class is applied, and the optional collapsible
body / click-to-expand traceback affordances mount only when the
underlying :class:`EventChip` carries content for them.

Also covers the updated :class:`ScoreChipWidget` visual: leading ``✓``
glyph, ``real`` CSS class (vs ``indicator`` mode), and the
``answer: …`` body row that lands ahead of the explanation.
"""

from __future__ import annotations

import re

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Static

from inspect_ai.agent._acp.tui.state import EventChip, ScoreChip
from inspect_ai.agent._acp.tui.widgets._collapsible import CollapsibleContent
from inspect_ai.agent._acp.tui.widgets.event_chip import (
    EventChipWidget,
    _CollapsibleJSON,
    _TracebackBlock,
)
from inspect_ai.agent._acp.tui.widgets.score import (
    ScoreChipWidget,
    _ExplanationBlock,
)

pytestmark = pytest.mark.slow


def _harness(widget_factory):
    """Build a one-shot Textual app hosting a single widget."""

    class _OneWidgetApp(App[None]):
        def compose(self) -> ComposeResult:
            yield widget_factory()

    return _OneWidgetApp()


_MARKUP_TAG = re.compile(r"\[(?:/?[^\[\]]*)\]")
"""Matches any Rich- or Textual-style markup tag (``[dim]`` / ``[$success]``
/ ``[/]`` etc.). We strip rather than parse because Rich's
``Text.from_markup`` doesn't recognise Textual's ``$token`` CSS
variables (they're resolved by Textual at render time against the
active theme, not by Rich's markup parser)."""


def _chip_plain(chip: Static) -> str:
    """Strip markup tags from chip content for substring assertions."""
    return _MARKUP_TAG.sub("", str(chip.content))


def _event_chip(
    *,
    kind: str = "info",
    header_summary: str = "info · subsystem",
    body_text: str | None = None,
    traceback: str | None = None,
    chip_id: str = "event-1",
    body_format: str = "markdown",
) -> EventChip:
    return EventChip(
        kind=kind,  # type: ignore[arg-type]
        header_summary=header_summary,
        body_text=body_text,
        chip_id=chip_id,
        traceback=traceback,
        body_format=body_format,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# EventChipWidget — per-kind rendering
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_renders_sample_limit_header() -> None:
    chip = _event_chip(kind="sample_limit", header_summary="limit · token")
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        # Per-kind CSS class drives the background tint rule.
        assert widget.has_class("kind-warning")
        rendered = _chip_plain(widget.query_one(".chip", Static))
        # Leading glyph + colored event word + dim separator + detail.
        assert "⚠" in rendered
        assert "limit" in rendered
        assert "token" in rendered


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_renders_error_header_and_traceback_block() -> None:
    chip = _event_chip(
        kind="error",
        header_summary="error · ValueError: bad input",
        body_text="ValueError: bad input",
        traceback="Traceback (most recent call last):\n  File a.py, line 1",
        body_format="plain",
    )
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        assert widget.has_class("kind-error")
        rendered = _chip_plain(widget.query_one(".chip", Static))
        assert "✗" in rendered
        assert "error" in rendered
        assert "ValueError" in rendered
        # Plain-format body skips ``CollapsibleContent`` so the body
        # sits flush against the chip header — Rich Markdown's
        # paragraph spacing would otherwise insert a blank row.
        assert list(widget.query(CollapsibleContent)) == []
        plain_body = widget.query_one(".event-body-plain", Static)
        assert "ValueError: bad input" in str(plain_body.content)
        # Traceback affordance mounted; starts collapsed.
        tb = widget.query_one(_TracebackBlock)
        assert tb.has_class("collapsed")


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_renders_compaction_header_with_token_delta() -> None:
    chip = _event_chip(
        kind="compaction",
        header_summary="compaction · summary · tokens 12.3k → 4.1k",
    )
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        assert widget.has_class("kind-accent")
        rendered = _chip_plain(widget.query_one(".chip", Static))
        assert "↺" in rendered
        assert "compaction" in rendered
        assert "12.3k" in rendered
        assert "4.1k" in rendered


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_renders_info_header_and_body() -> None:
    """Info chips use the manila ``kind-info`` class (not cyan ``kind-accent``).

    Info and compaction used to share the cyan accent which made them
    read as the same chip family at a glance. Info now wears a
    yellow/manila tint so the two are visually distinct — info has
    the same hue as system messages (both are "subsystem spoke up"
    signals).
    """
    chip = _event_chip(
        kind="info",
        header_summary="info · subsystem",
        body_text="subsystem ready",
    )
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        assert widget.has_class("kind-info")
        assert not widget.has_class("kind-accent")
        rendered = _chip_plain(widget.query_one(".chip", Static))
        assert "ⓘ" in rendered
        assert "info" in rendered
        ccs = list(widget.query(CollapsibleContent))
        assert any("subsystem ready" in cc._full_text for cc in ccs)


# ---------------------------------------------------------------------------
# EventChipWidget — body-less / traceback-less variants
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_with_no_body_skips_body_container() -> None:
    chip = _event_chip(kind="info", header_summary="info", body_text=None)
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        # No CollapsibleContent mounted at all when there's nothing to show.
        assert not list(widget.query(CollapsibleContent))
        assert not list(widget.query(_TracebackBlock))


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_error_without_traceback_skips_traceback_block() -> None:
    chip = _event_chip(
        kind="error",
        header_summary="error · oops",
        body_text="oops",
        traceback=None,
    )
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        # Body mounts (for the message) but no traceback affordance.
        assert list(widget.query(CollapsibleContent))
        assert not list(widget.query(_TracebackBlock))


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_header_without_separator_renders_bare_event_word() -> None:
    """Headers like ``"error"`` (no ``·`` details) still render cleanly."""
    chip = _event_chip(kind="error", header_summary="error", body_text=None)
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        rendered = _chip_plain(widget.query_one(".chip", Static))
        # Glyph + event word, no trailing dim separators.
        assert "✗" in rendered
        assert "error" in rendered
        # Crude check: no orphan ``·`` from a missing-tail bug.
        assert "·" not in rendered


# ---------------------------------------------------------------------------
# _TracebackBlock toggle
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_traceback_block_toggle_expands_and_collapses_on_click() -> None:
    block = _TracebackBlock(
        "Traceback (most recent call last):\n  File a.py, line 1\n    raise X"
    )
    app = _harness(lambda: block)
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one(_TracebackBlock)
        assert tb.has_class("collapsed")
        # Synthesise the click handler directly — the widget's CSS
        # query for the body wouldn't intersect a programmatic mouse
        # click event in the pilot reliably across Textual versions.
        tb.on_click()
        await pilot.pause()
        assert not tb.has_class("collapsed")
        tb.on_click()
        await pilot.pause()
        assert tb.has_class("collapsed")


# ---------------------------------------------------------------------------
# _CollapsibleJSON cap + toggle
# ---------------------------------------------------------------------------


def _multiline_json_body(line_count: int) -> str:
    """Build a JSON object whose pretty-printed form exceeds the line cap.

    Produces a dict with ``line_count`` keys so the rendered JSON has
    more lines than ``_EVENT_BODY_MAX_LINES``; the truncation note
    then actually mounts and the toggle behavior is exercisable.
    """
    import json as _json

    data = {f"k{i}": i for i in range(line_count)}
    return _json.dumps(data, indent=2)


@skip_if_trio
@pytest.mark.anyio
async def test_collapsible_json_renders_truncation_note_when_body_exceeds_cap() -> None:
    body = _multiline_json_body(20)
    block = _CollapsibleJSON(body, max_lines=8)
    app = _harness(lambda: block)
    async with app.run_test() as pilot:
        await pilot.pause()
        cj = app.query_one(_CollapsibleJSON)
        # Note is mounted with the omitted-line count.
        note = cj.query_one("#json-note", Static)
        assert "more line" in str(note.content)
        # Body shows only the cap, not the full payload.
        body_static = cj.query_one("#json-body", Static)
        rendered = str(body_static.content.plain)
        assert "k0" in rendered
        # k19 is past the cap so it shouldn't be in the visible body.
        assert "k19" not in rendered


@skip_if_trio
@pytest.mark.anyio
async def test_collapsible_json_skips_note_when_body_fits() -> None:
    """Small JSON payloads render fully with no clickable note."""
    block = _CollapsibleJSON('{"a": 1}', max_lines=8)
    app = _harness(lambda: block)
    async with app.run_test() as pilot:
        await pilot.pause()
        cj = app.query_one(_CollapsibleJSON)
        assert not list(cj.query("#json-note"))


@skip_if_trio
@pytest.mark.anyio
async def test_collapsible_json_toggle_expands_and_collapses_on_click() -> None:
    body = _multiline_json_body(20)
    block = _CollapsibleJSON(body, max_lines=8)
    app = _harness(lambda: block)
    async with app.run_test() as pilot:
        await pilot.pause()
        cj = app.query_one(_CollapsibleJSON)
        body_static = cj.query_one("#json-body", Static)
        # Collapsed: late keys absent.
        assert "k19" not in str(body_static.content.plain)
        cj.on_click()
        await pilot.pause()
        # Expanded: full payload visible, note flips to "collapse".
        assert "k19" in str(body_static.content.plain)
        note = cj.query_one("#json-note", Static)
        assert "collapse" in str(note.content)
        cj.on_click()
        await pilot.pause()
        # Collapsed again: late keys gone, note reverts to count.
        assert "k19" not in str(body_static.content.plain)
        assert "more line" in str(note.content)


@skip_if_trio
@pytest.mark.anyio
async def test_collapsible_json_click_with_no_overflow_is_noop() -> None:
    """A click on a body that fits doesn't toggle into a "collapsed" state.

    The widget never mounted a note in this case, so toggling would
    silently shrink visible content with no way to bring it back.
    """
    block = _CollapsibleJSON('{"a": 1}', max_lines=8)
    app = _harness(lambda: block)
    async with app.run_test() as pilot:
        await pilot.pause()
        cj = app.query_one(_CollapsibleJSON)
        body_static = cj.query_one("#json-body", Static)
        before = str(body_static.content.plain)
        cj.on_click()
        await pilot.pause()
        after = str(body_static.content.plain)
        assert before == after


@skip_if_trio
@pytest.mark.anyio
async def test_event_chip_with_json_body_mounts_collapsible_json() -> None:
    """JSON-format info body lands in the JSON-specific collapsible widget.

    Asserts :class:`_CollapsibleJSON` is used and the markdown-backed
    :class:`CollapsibleContent` is NOT — keeps the chip's tinted band
    visible behind the JSON body instead of being painted over by a
    fenced code-block background.
    """
    chip = _event_chip(
        kind="info",
        header_summary="info · metrics",
        body_text=_multiline_json_body(20),
        body_format="json",
    )
    app = _harness(lambda: EventChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(EventChipWidget)
        assert list(widget.query(_CollapsibleJSON))
        assert not list(widget.query(CollapsibleContent))


# ---------------------------------------------------------------------------
# ScoreChipWidget — updated visual + answer line
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_renders_star_glyph_and_neutral_class() -> None:
    """Every real score chip gets the ``★`` glyph + purple ``neutral`` class.

    We dropped the green ``passed`` variant — chip styling no longer
    encodes a pass/fail verdict because many real scorers emit
    continuous values where pass/fail isn't well-defined. The value
    text carries the meaning; the chip just signals "score landed".
    """
    chip = ScoreChip(
        scorer="exact-match",
        value="C",
        passed=True,
        reason="matches target",
        chip_id="score-1",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        # Always-purple ``neutral`` class — no green ``passed``
        # variant; ``indicator`` is for in-flight chips only.
        assert widget.has_class("neutral")
        assert not widget.has_class("passed")
        rendered = _chip_plain(widget.query_one(".chip", Static))
        # Leading ``★`` "this is a score" glyph + ``score`` event
        # word.
        assert "★" in rendered
        assert "score" in rendered
        assert "exact-match" in rendered
        # Verdict words ``passed`` / ``failed`` were dropped — they
        # promoted a binary verdict the score values don't carry.
        assert "passed" not in rendered
        assert "failed" not in rendered


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_body_renders_answer_collapsible_and_explanation_block() -> (
    None
):
    """Answer rides through standard CollapsibleContent; explanation behind expander.

    Mirrors the reasoning / traceback affordance — short bits stay
    visible, the long rationale only renders when the operator opts in.
    """
    chip = ScoreChip(
        scorer="s",
        value="C",
        passed=True,
        reason="matches target",
        chip_id="score-2",
        answer="42",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        # Answer body mounts as the standard CollapsibleContent so it
        # picks up the shared "… N more lines" truncation affordance.
        ccs = list(widget.query(CollapsibleContent))
        assert len(ccs) == 1
        assert "answer: 42" in ccs[0]._full_text
        # Explanation lives behind the click-to-expand block.
        blocks = list(widget.query(_ExplanationBlock))
        assert len(blocks) == 1
        assert blocks[0].has_class("collapsed")
        # Single-line answer → no extra top margin on the explanation.
        assert not blocks[0].has_class("after-multiline-answer")


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_body_omits_answer_when_unset() -> None:
    """No CollapsibleContent when the chip has no answer — the link still mounts."""
    chip = ScoreChip(
        scorer="s",
        value="C",
        passed=True,
        reason="matches target",
        chip_id="score-3",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        assert not list(widget.query(CollapsibleContent))
        # The explanation block still mounts when only ``reason`` is set.
        assert len(list(widget.query(_ExplanationBlock))) == 1


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_with_only_answer_skips_explanation_block() -> None:
    """Chip with answer but no reason renders the answer body only — no link."""
    chip = ScoreChip(
        scorer="s",
        value="C",
        passed=True,
        reason=None,
        chip_id="score-only-answer",
        answer="42",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        assert len(list(widget.query(CollapsibleContent))) == 1
        # No explanation block when the reason is empty — the link
        # would otherwise be a dead affordance.
        assert not list(widget.query(_ExplanationBlock))


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_multiline_answer_mounts_explicit_gap_spacer() -> None:
    """Multi-line answer mounts a real 1-row spacer between answer and explanation.

    We used to drive the gap via a ``margin-top`` CSS rule on the
    explanation block, but Textual reflowed the margin away whenever
    the operator clicked to expand either the answer or the
    explanation — the two affordances ended up reading flush against
    each other after the first expand. An explicit spacer Static
    survives reflows because it's a real widget with ``height: 1``.
    """
    multiline_answer = "line 1\nline 2\nline 3"
    chip = ScoreChip(
        scorer="s",
        value="C",
        passed=True,
        reason="rubric notes",
        chip_id="score-multiline",
        answer=multiline_answer,
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        spacers = list(widget.query(".answer-explanation-gap"))
        assert len(spacers) == 1


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_single_line_answer_omits_gap_spacer() -> None:
    """Single-line answer keeps the layout tight — no spacer between answer and explanation."""
    chip = ScoreChip(
        scorer="s",
        value="C",
        passed=True,
        reason="rubric notes",
        chip_id="score-single",
        answer="42",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        assert not list(widget.query(".answer-explanation-gap"))


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_explanation_block_toggle_expands_and_collapses() -> None:
    """Click the ``explanation`` link to expand; click again to collapse."""
    chip = ScoreChip(
        scorer="s",
        value="C",
        passed=True,
        reason="lengthy rubric rationale",
        chip_id="score-toggle",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.query_one(_ExplanationBlock)
        assert block.has_class("collapsed")
        block.on_click()
        assert not block.has_class("collapsed")
        block.on_click()
        assert block.has_class("collapsed")


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_indicator_mode_renders_spinner_and_scorer_name() -> None:
    """Indicator chip renders ``<spinner> score · <scorer> · <elapsed>``.

    Stays visually quiet (no green/purple background tint), uses the
    same braille spinner as the assistant chip, and shows elapsed
    seconds where the value would be on a terminal score chip.
    """
    import time

    started = time.monotonic() - 3.5  # simulate "3.5s ago"
    chip = ScoreChip(
        scorer=None,
        value="",
        passed=None,
        reason="scoring · my-scorer…",
        chip_id="score-ind-1",
        span_id="sp-1",
        started_at=started,
        scorer_name="my-scorer",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        assert widget.has_class("indicator")
        # Indicator state is mutually exclusive with the
        # outcome-tinted ``passed`` / ``neutral`` classes so the
        # placeholder stays visually quiet.
        assert not widget.has_class("passed")
        assert not widget.has_class("neutral")
        # Indicator chips don't mount a body — the reason is rendered
        # inline in the chip line.
        assert not list(widget.query(CollapsibleContent))
        rendered = _chip_plain(widget.query_one(".chip", Static))
        # ``score`` event word + scorer name + elapsed timer; no
        # ``★`` glyph (spinner takes its place) and no ``scoring · ``
        # prefix (the spinner + ``score`` already say it's in flight).
        assert "score" in rendered
        assert "my-scorer" in rendered
        # Elapsed time renders as ``Ns`` / similar via format_duration.
        assert "s" in rendered  # seconds suffix from format_duration


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_indicator_tick_advances_spinner_and_timer() -> None:
    """``tick_spinner`` re-renders the chip with a fresh spinner frame."""
    import time

    chip = ScoreChip(
        scorer=None,
        value="",
        passed=None,
        reason="scoring · slow-scorer…",
        chip_id="score-ind-tick",
        span_id="sp-tick",
        started_at=time.monotonic(),
        scorer_name="slow-scorer",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        before = _chip_plain(widget.query_one(".chip", Static))
        # Advance one frame; the spinner glyph rotates so the chip
        # text should change.
        widget.tick_spinner()
        await pilot.pause()
        after = _chip_plain(widget.query_one(".chip", Static))
        assert before != after


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_terminal_tick_spinner_is_noop() -> None:
    """Real (terminal) score chips ignore ``tick_spinner`` — nothing to animate."""
    chip = ScoreChip(
        scorer="exact-match",
        value="C",
        passed=True,
        reason="matches target",
        chip_id="score-terminal",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        before = _chip_plain(widget.query_one(".chip", Static))
        widget.tick_spinner()
        await pilot.pause()
        after = _chip_plain(widget.query_one(".chip", Static))
        # No-op — the terminal chip's text is invariant.
        assert before == after


@skip_if_trio
@pytest.mark.anyio
async def test_score_chip_neutral_value_renders_star_glyph_and_neutral_class() -> None:
    """Anything that isn't an unambiguous 1.0 pass gets the ``neutral`` (cyan) class.

    Same ``★`` glyph as a pass — the icon is about "this is a
    score", not a verdict. Colour alone signals pass-vs-neutral so
    the chip doesn't misclaim a failure it can't prove (a partial
    score isn't a failure, and a plain ``0`` could mean different
    things by rubric). ``passed=None`` here represents an ``"I"`` /
    partial / numeric / non-scalar score routed through
    :func:`_classify_score_value`.
    """
    chip = ScoreChip(
        scorer="exact",
        value="I",
        passed=None,
        reason="wrong",
        chip_id="score-4",
    )
    app = _harness(lambda: ScoreChipWidget(chip))
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one(ScoreChipWidget)
        assert widget.has_class("neutral")
        assert not widget.has_class("passed")
        rendered = _chip_plain(widget.query_one(".chip", Static))
        assert "★" in rendered
        assert "score" in rendered
        assert "exact" in rendered
        # No ✗ "failed" glyph — we never claim failure visually.
        assert "✗" not in rendered
        assert "passed" not in rendered
        assert "failed" not in rendered
