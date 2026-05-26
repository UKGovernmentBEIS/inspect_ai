"""Tests for the plan strip + overlay widgets.

Two layers:

- **Pure-function / pure-state tests** (no event loop) exercise the
  strip's body formatter and the overlay row classifier so the visual
  vocabulary (glyphs, dim/bright hierarchy, status classes) is pinned
  without spinning up Textual.
- **Pilot tests** (marked ``slow`` via module-level ``pytestmark``)
  drive the full screen lifecycle: hidden-when-no-plan, visible after
  AgentPlanUpdate, ``^p`` opens the overlay, ``esc`` / ``^p`` /
  ``x``-click dismiss, overlay opens scrolled to the bottom for long
  plans.
"""

from __future__ import annotations

from typing import Any

import pytest
from acp.schema import (
    AgentPlanUpdate,
    PlanEntry,
    SessionNotification,
)
from test_helpers.utils import skip_if_trio
from textual.css.query import NoMatches
from textual.widgets import Static

from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.session_screen import SessionScreen
from inspect_ai.agent._acp.tui.widgets.plan import (
    PlanOverlayScreen,
    PlanStripWidget,
)

from .conftest import make_fake_client

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _entry(content: str, status: str = "pending") -> PlanEntry:
    return PlanEntry(content=content, status=status, priority="medium")  # type: ignore[arg-type]


def _plan_notification(*entries: PlanEntry) -> SessionNotification:
    return SessionNotification(
        session_id="sid",
        update=AgentPlanUpdate(session_update="plan", entries=list(entries)),
    )


# ---------------------------------------------------------------------------
# Pure-function tests for PlanStripWidget._format_body
# ---------------------------------------------------------------------------


def test_format_body_empty_plan_renders_no_entries_placeholder() -> None:
    """Forward-compat: an explicitly empty plan shouldn't render as garbage."""
    text = PlanStripWidget._format_body(done=0, total=0, current=None)
    assert "no entries" in text
    assert "0/0" in text


def test_format_body_all_complete_says_so() -> None:
    text = PlanStripWidget._format_body(done=3, total=3, current=None)
    assert "all complete" in text
    assert "3/3" in text


def test_format_body_with_current_omits_row_status_glyph() -> None:
    """The collapsed strip body has NO ``[◐]`` / ``[ ]`` glyph next to ``current:``.

    The row-status icon lives in the expanded overlay only. On the
    strip it'd be redundant chrome that competes with the task title
    for attention. The check glyph in ``[✓ done/total]`` (a
    different chip) is fine — it's the tally marker, not a
    per-row indicator.
    """
    current = _entry("ship it", status="in_progress")
    text = PlanStripWidget._format_body(done=1, total=3, current=current)
    # No row-status glyph anywhere between the tally and the task.
    assert "\\[◐]" not in text
    assert "\\[ ]" not in text
    # But the content + tally + label are all there.
    assert "ship it" in text
    assert "1/3" in text
    assert "current:" in text


def test_format_body_pending_also_omits_glyph() -> None:
    current = _entry("write tests", status="pending")
    text = PlanStripWidget._format_body(done=2, total=4, current=current)
    assert "\\[ ]" not in text
    assert "\\[◐]" not in text
    assert "write tests" in text


def test_format_body_escapes_markup_in_content() -> None:
    """Literal ``[`` in user content can't bleed into Rich markup."""
    from rich.console import Console
    from rich.text import Text

    current = _entry("[draft] write tests", status="pending")
    text = PlanStripWidget._format_body(done=0, total=1, current=current)
    # The escaped source still contains the bracket text but with
    # a backslash prefix so Rich renders it literally.
    assert "\\[draft]" in text
    # End-to-end: feeding the markup through Rich must NOT raise and
    # must yield "[draft]" in the rendered plain text.
    console = Console(width=200, no_color=True, force_terminal=False)
    rendered = console.render_str(text).plain
    assert "[draft] write tests" in rendered
    # Sanity: the result is a Text we can render without error.
    assert isinstance(console.render_str(text), Text)


def test_format_body_handles_backslash_before_bracket() -> None:
    r"""``r"\[/dim]"``-style content can't smuggle a fake closing tag.

    Regression for the earlier hand-rolled ``text.replace("[", "\[")``
    which left existing backslashes untouched — Rich would then read
    the doubled-up backslash as an escape and treat the following
    bracket as live markup, raising MarkupError or leaking styles
    into the strip. ``rich.markup.escape`` handles the backslash by
    doubling it BEFORE escaping the bracket.
    """
    from rich.console import Console

    payload = r"\[/dim]bad"
    current = _entry(payload, status="pending")
    text = PlanStripWidget._format_body(done=0, total=1, current=current)
    console = Console(width=200, no_color=True, force_terminal=False)
    rendered = console.render_str(text).plain
    # The literal payload must appear in the rendered text verbatim,
    # NOT be interpreted as a closing ``/dim`` tag.
    assert payload in rendered, (
        f"backslash + bracket payload should round-trip literally; "
        f"got rendered={rendered!r}"
    )


# ---------------------------------------------------------------------------
# Pure-function tests for PlanOverlayScreen row classification
# ---------------------------------------------------------------------------


def test_overlay_row_classes_marks_in_progress() -> None:
    classes = PlanOverlayScreen._row_classes(_entry("x", "in_progress"))
    assert "-running" in classes
    assert "plan-row" in classes


def test_overlay_row_classes_marks_completed() -> None:
    classes = PlanOverlayScreen._row_classes(_entry("x", "completed"))
    assert "-completed" in classes


def test_overlay_row_classes_pending_has_no_state_class() -> None:
    """Pending rows use the bare ``plan-row`` class — no state suffix."""
    classes = PlanOverlayScreen._row_classes(_entry("x", "pending"))
    assert classes == "plan-row"


def test_overlay_row_markup_uses_status_glyph() -> None:
    text = PlanOverlayScreen._row_markup(_entry("do thing", "in_progress"))
    # Glyph is Rich-escaped at the source (``\\[`` → literal ``[``);
    # rendered terminal output is ``[◐] do thing``.
    assert text.startswith("\\[◐]")
    assert "do thing" in text


# ---------------------------------------------------------------------------
# Pilot tests
# ---------------------------------------------------------------------------


async def _open_session_screen(pilot: Any, rows: list[SessionRow]) -> SessionScreen:
    """Walk PickerScreen → SessionScreen via the picker's ``_on_select``.

    Same pattern as the existing session-screen pilot tests
    (see test_session_screen.py): trigger the picker callback
    synchronously, then poll up to 20 ticks for the worker-spawned
    attach to land on the new screen. Returns the SessionScreen so
    the caller can grab state / widgets off it.
    """
    app = pilot.app
    await pilot.pause()
    if not isinstance(app.screen, SessionScreen):
        app.screen._on_select(rows[0])
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
    assert isinstance(app.screen, SessionScreen)
    return app.screen


def _sample_row() -> SessionRow:
    """Minimal session row for pilot tests."""
    from pathlib import Path

    from inspect_ai.agent._acp.discovery import TargetAddress

    return SessionRow(
        eval_id="eval-x",
        session_id="sid-x",
        task="t",
        sample_id="s1",
        epoch=1,
        agent_name="react",
        started_at=1_700_000_000.0,
        target=TargetAddress(socket_path=Path("/tmp/acp_plan_test.sock")),
    )


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_plan_strip_hidden_when_no_plan() -> None:
    """No AgentPlanUpdate yet → strip carries the hidden class."""
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        strip = screen.query_one(PlanStripWidget)
        assert strip.has_class("-hidden"), (
            "strip should be hidden before any plan update arrives"
        )


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_plan_strip_appears_on_plan_update() -> None:
    """First AgentPlanUpdate flips the strip visible + sets the body text."""
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.consume(
            _plan_notification(
                _entry("write tests", "completed"),
                _entry("ship it", "in_progress"),
            )
        )
        await pilot.pause()
        strip = screen.query_one(PlanStripWidget)
        assert not strip.has_class("-hidden")
        body = strip.query_one("#plan-strip-body", Static)
        # ``Static.render()`` returns the Rich renderable; ``str()``
        # collapses it to plain text via Rich's __rich_console__
        # render path. Robust across the Static.renderable rename in
        # newer Textual.
        rendered = str(body.render())
        assert "1/2" in rendered
        assert "ship it" in rendered


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_plan_strip_hides_when_scoring_phase_begins() -> None:
    """Outer ``span(name="scorers")`` event hides the plan strip.

    Agent loop is done by the time the scoring boundary fires —
    leaving the plan visible during scoring reads as "still working
    on it" even though we've moved on to scoring. The state-level
    clearing is covered in ``test_scoring.py``; this exercises the
    full path through the widget subscriber so a regression in the
    re-render or display:none CSS gets caught.
    """
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.consume(_plan_notification(_entry("step 1", "completed")))
        await pilot.pause()
        strip = screen.query_one(PlanStripWidget)
        assert not strip.has_class("-hidden"), (
            "precondition: plan should be visible before scoring starts"
        )
        # Fire the outer scoring boundary via the same client-side route
        # the server's ``inspect/event`` notification would land in.
        # ``util._span.span`` defaults ``type`` to ``name`` when the
        # caller omits it — so the wire payload for ``span(name=
        # "scorers")`` carries ``type="scorers"`` (not ``None``).
        screen.state.consume_inspect_event(
            {
                "event": "span_begin",
                "id": "s-out",
                "name": "scorers",
                "type": "scorers",
            }
        )
        await pilot.pause()
        assert strip.has_class("-hidden"), "scoring boundary should hide the plan strip"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_p_toggles_plan_overlay() -> None:
    """``^p`` while a plan exists pushes the overlay; pressing it again pops."""
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.consume(_plan_notification(_entry("first", "in_progress")))
        await pilot.pause()

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen), (
            f"expected overlay on top, got {type(app.screen).__name__}"
        )

        # Close via the overlay's own ^p binding (priority).
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, SessionScreen)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_p_noop_when_no_plan() -> None:
    """``^p`` before any plan exists must not open an empty overlay."""
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+p")
        await pilot.pause()
        # Still on the SessionScreen — no overlay was pushed.
        assert isinstance(app.screen, SessionScreen)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_overlay_dismisses_on_escape() -> None:
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.consume(_plan_notification(_entry("only", "pending")))
        await pilot.pause()

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SessionScreen)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_overlay_scrolls_past_completed_items_on_open() -> None:
    """On open, the overlay scrolls past completed rows.

    Builds a plan with 10 completed rows followed by 10 pending
    (last in_progress). Opening the overlay should land the viewport
    such that the first non-completed row is visible at / near the
    top — completed history is scrolled off, the operator's eye
    drops onto the active work.
    """
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test(size=(120, 20)) as pilot:
        screen = await _open_session_screen(pilot, rows)

        long_plan = [_entry(f"done #{i}", "completed") for i in range(10)]
        long_plan += [_entry(f"todo #{i}", "pending") for i in range(10)]
        long_plan[10] = _entry("active", "in_progress")
        screen.state.consume(_plan_notification(*long_plan))
        await pilot.pause()

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen)
        try:
            scroll = app.screen.query_one("#plan-overlay-rows")
        except NoMatches:
            pytest.fail("overlay missing #plan-overlay-rows VerticalScroll")
        # Should have scrolled past the completed prefix — scroll_y > 0
        # (didn't open at top) and <= max_scroll_y. The exact pixel
        # depends on row layout; the contract under test is "moved
        # past the completed block."
        assert scroll.scroll_y > 0, (
            "overlay should have scrolled past completed rows on open; "
            f"scroll_y={scroll.scroll_y}, max={scroll.max_scroll_y}"
        )


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_overlay_focuses_in_progress_row_even_with_earlier_pending() -> None:
    """Overlay scrolls to the in_progress row, not the first pending row.

    Builds a plan where a pending row precedes the in_progress row.
    The strip's "current" derivation prefers in_progress, so the
    overlay must too — otherwise the strip says "current: B" while
    the overlay opens on row A above it. Regression for the prior
    overlay-side implementation that ran its own first-non-completed
    scan (which would have landed on the earlier pending row).
    """
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test(size=(120, 20)) as pilot:
        screen = await _open_session_screen(pilot, rows)

        # 20 entries: half completed prefix, then a long pending
        # block with an in_progress row near the END. A naive
        # first-non-completed scan would land on row 10 (first
        # pending); the strip's logic + ours should land on the
        # in_progress row (row 18).
        long_plan = [_entry(f"done #{i}", "completed") for i in range(10)]
        long_plan += [_entry(f"pending #{i}", "pending") for i in range(10)]
        long_plan[18] = _entry("THE ACTIVE ROW", "in_progress")
        screen.state.consume(_plan_notification(*long_plan))
        await pilot.pause()

        # Strip + state should agree the in_progress row at index 18
        # is current.
        assert screen.state.plan_current_index == 18
        assert screen.state.plan_current_entry is not None
        assert screen.state.plan_current_entry.content == "THE ACTIVE ROW"

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen)
        try:
            scroll = app.screen.query_one("#plan-overlay-rows")
        except NoMatches:
            pytest.fail("overlay missing #plan-overlay-rows VerticalScroll")
        # Scroll must be past row 10 (where a first-non-completed
        # implementation would have stopped). With a 20-entry plan
        # and a small viewport, row 18 requires near-max scroll;
        # the naive scan would have landed near scroll_y ~= 10.
        assert scroll.scroll_y >= scroll.max_scroll_y - 1, (
            "overlay should land on the in_progress row near the end "
            f"of the list; got scroll_y={scroll.scroll_y}, "
            f"max={scroll.max_scroll_y} (a regression in "
            "_auto_scroll / plan_current_index would land much "
            "earlier on the first pending row at index 10)"
        )


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_overlay_scrolls_to_bottom_when_all_completed() -> None:
    """Fallback: if every entry is completed, scroll to bottom.

    No "first non-completed" exists — surfacing the most recent
    completion at the bottom is the meaningful anchor.
    """
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test(size=(120, 20)) as pilot:
        screen = await _open_session_screen(pilot, rows)

        long_plan = [_entry(f"done #{i}", "completed") for i in range(30)]
        screen.state.consume(_plan_notification(*long_plan))
        await pilot.pause()

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen)
        try:
            scroll = app.screen.query_one("#plan-overlay-rows")
        except NoMatches:
            pytest.fail("overlay missing #plan-overlay-rows VerticalScroll")
        assert scroll.scroll_y == scroll.max_scroll_y, (
            f"all-completed plan should scroll to bottom; "
            f"got scroll_y={scroll.scroll_y}, max={scroll.max_scroll_y}"
        )


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_overlay_reflects_plan_updates_while_open() -> None:
    """A new ``AgentPlanUpdate`` while the overlay is open updates rows in place.

    Opens the overlay with row 0 in_progress, then fires a state
    update marking row 0 completed + row 1 in_progress. The header
    tally and per-row classes update without re-opening the overlay.
    """
    from textual.widgets import Static

    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.consume(
            _plan_notification(
                _entry("first", "in_progress"),
                _entry("second", "pending"),
                _entry("third", "pending"),
            )
        )
        await pilot.pause()

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen)

        # Snapshot the initial row classes — row 0 is the runner.
        row_widgets_before = [w for w in app.screen.query("#plan-overlay-rows Static")]
        assert row_widgets_before[0].has_class("-running")
        assert not row_widgets_before[1].has_class("-running")

        # Fire a plan progression: row 0 done, row 1 now running.
        screen.state.consume(
            _plan_notification(
                _entry("first", "completed"),
                _entry("second", "in_progress"),
                _entry("third", "pending"),
            )
        )
        await pilot.pause()

        # Still on the overlay — no close/reopen.
        assert isinstance(app.screen, PlanOverlayScreen)
        # Same widget instances (in-place update), updated classes.
        row_widgets_after = [w for w in app.screen.query("#plan-overlay-rows Static")]
        # Length matches → in-place update path was taken; widgets
        # should be the SAME instances as before.
        assert len(row_widgets_after) == len(row_widgets_before)
        for before, after in zip(row_widgets_before, row_widgets_after):
            assert before is after, (
                "in-place update should reuse widget instances; "
                "rebuild path indicates the row count drifted"
            )
        assert row_widgets_after[0].has_class("-completed")
        assert row_widgets_after[1].has_class("-running")
        # Header tally updated too.
        header = app.screen.query_one("#plan-overlay-header-label", Static)
        assert "1/3" in str(header.render())


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_footer_hides_plan_binding_until_first_plan_arrives() -> None:
    """The ^p footer slot is fully gone — not visible-but-disabled — pre-plan.

    Tests ``Screen.active_bindings`` directly (which is what the
    footer reads) rather than ``check_action``'s return value, so
    we catch the Textual 8.2.3 quirk where ``check_action`` returning
    ``None`` would still render the binding as a greyed-out slot
    (only the literal ``False`` causes the binding to be filtered
    out of ``active_bindings``).
    """
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)

        # Pre-plan: ``toggle_plan`` must not appear in active_bindings
        # at all. Otherwise the footer renders an inert "plan" hint.
        # ActiveBinding is a NamedTuple of (node, binding, enabled,
        # tooltip); ``binding.action`` carries the action name.
        actions_before = {b.binding.action for b in screen.active_bindings.values()}
        assert "toggle_plan" not in actions_before, (
            f"toggle_plan binding should be filtered out before any "
            f"plan arrives; got {actions_before}"
        )

        # Post-plan: it appears and is enabled.
        screen.state.consume(_plan_notification(_entry("first", "in_progress")))
        await pilot.pause()
        post = screen.active_bindings
        toggle_entries = [b for b in post.values() if b.binding.action == "toggle_plan"]
        assert len(toggle_entries) == 1, (
            f"toggle_plan should appear exactly once after plan arrives; "
            f"got {[b.binding.action for b in post.values()]}"
        )
        assert toggle_entries[0].enabled is True


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_plan_strip_click_opens_overlay() -> None:
    """Clicking the strip is the mouse parity for ``^p``."""
    rows = [_sample_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.consume(_plan_notification(_entry("active", "in_progress")))
        await pilot.pause()

        await pilot.click(PlanStripWidget)
        await pilot.pause()
        assert isinstance(app.screen, PlanOverlayScreen)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_session_screen_binds_ctrl_p_to_toggle_plan() -> None:
    """Pin the binding wiring — keeps the footer hint + action stable."""
    from textual.binding import Binding

    bindings = {b.key: b for b in SessionScreen.BINDINGS if isinstance(b, Binding)}
    assert "ctrl+p" in bindings
    b = bindings["ctrl+p"]
    assert b.action == "toggle_plan"
    assert b.show is True
