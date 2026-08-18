"""Pilot tests for the deferred-body parallel-tools rendering gate.

Under parallel tool execution, every tool card collapses to its
single-line header — both the call-view (input preview, e.g. a custom
viewer's ``lookup ACME`` markdown) and the eventual result body are
held back while ANY other tool is still actively running. The reveal
fires together: when the last in-flight tool transitions to a terminal
state, the natural ``SessionState`` notification chains through
``TranscriptWidget.refresh_from`` and unblocks every held card in one
pass, so they all mount in declared order.

The widget-level behaviour (skip body mount when ``defer_body=True``,
rebuild wholesale when the gate flips back to False) lives in
:class:`ToolCallWidget`. The transcript-level wiring (compute
``defer_body`` per item, include it in the fingerprint, route it
through ``update_state``) lives in :class:`TranscriptWidget`. This
file exercises both together against a real ``InspectAcpApp.run_test``
pilot so we know the reactive chain actually fires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from acp.schema import (
    ContentToolCallContent,
    FileEditToolCallContent,
    SessionNotification,
    TerminalToolCallContent,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)
from test_helpers.utils import skip_if_trio
from textual.widgets import Static

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.session_screen import SessionScreen
from inspect_ai.agent._acp.tui.widgets._collapsible import CollapsibleContent
from inspect_ai.agent._acp.tui.widgets.tool_call import ToolCallWidget

from .conftest import make_fake_client


def _row() -> SessionRow:
    return SessionRow(
        eval_id="eval-x",
        session_id="sid-x",
        task="t",
        sample_id="s1",
        epoch=1,
        agent_name="react",
        started_at=1_700_000_000.0,
        target=TargetAddress(socket_path=Path("/tmp/acp_defer_body_test.sock")),
        fails_on_error=False,
    )


async def _open_session_screen(pilot: Any, rows: list[SessionRow]) -> SessionScreen:
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


def _push_tool_start(
    screen: SessionScreen,
    tool_call_id: str,
    *,
    call_view_text: str | None = None,
) -> None:
    """Inject a ToolCallStart notification.

    When ``call_view_text`` is supplied, the start carries a body
    content block — mirroring what a tool with a registered viewer
    (e.g. the bash command preview) emits the moment the call lands.
    """
    content: (
        list[ContentToolCallContent | FileEditToolCallContent | TerminalToolCallContent]
        | None
    ) = (
        [
            ContentToolCallContent(
                type="content",
                content=TextContentBlock(type="text", text=call_view_text),
            )
        ]
        if call_view_text is not None
        else None
    )
    start = ToolCallStart(
        session_update="tool_call",
        tool_call_id=tool_call_id,
        title=f"bash {tool_call_id}",
        status="in_progress",
        raw_input={"command": f"echo {tool_call_id}"},
        content=content,
    )
    screen._state.consume(SessionNotification(session_id="sid-x", update=start))


def _push_tool_complete_with_content(
    screen: SessionScreen, tool_call_id: str, body_text: str
) -> None:
    """Drive a completed status with a TextContentBlock body."""
    prog = ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id=tool_call_id,
        status="completed",
        content=[
            ContentToolCallContent(
                type="content",
                content=TextContentBlock(type="text", text=body_text),
            )
        ],
    )
    screen._state.consume(SessionNotification(session_id="sid-x", update=prog))


def _widget_for(screen: SessionScreen, tool_call_id: str) -> ToolCallWidget:
    for widget in screen.query(ToolCallWidget):
        if widget._state.tool_call_id == tool_call_id:
            return widget
    raise AssertionError(f"no ToolCallWidget for {tool_call_id!r}")


def _body_text(widget: ToolCallWidget) -> str:
    """Concatenate the mounted body's rendered text — empty when deferred.

    Tool-call result bodies use :class:`CollapsibleContent` (its
    ``_full_text`` is the source-of-truth for the markdown payload);
    plain ``Static`` fall-backs are used for diff / placeholder content.
    Walk both so the helper works across body variants.
    """
    try:
        body = widget.query_one(".body")
    except Exception:
        return ""
    out: list[str] = []
    for cc in body.walk_children(CollapsibleContent):
        out.append(cc._full_text)
    for st in body.walk_children(Static):
        try:
            out.append(str(st.renderable))  # type: ignore[attr-defined]
        except Exception:
            pass
    return "\n".join(out)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_completed_tool_body_held_while_sibling_in_flight() -> None:
    """B finishes while A still running → B's body is NOT mounted yet."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-A")
        _push_tool_start(screen, "tc-B")
        await pilot.pause()

        # B completes with content; A still in flight.
        _push_tool_complete_with_content(screen, "tc-B", "B-result-payload")
        await pilot.pause()

        # State-level: B has the content, status is terminal.
        b_state = screen._state._tool_calls_by_id["tc-B"]
        assert b_state.is_terminal
        assert b_state.content, "B's content should be on state"

        # DOM-level: B's body has not been mounted yet.
        b_widget = _widget_for(screen, "tc-B")
        assert "B-result-payload" not in _body_text(b_widget), (
            "B's result body must not appear while sibling tc-A is still running"
        )
        # The header HAS updated (status glyph + duration) — only the body
        # is held back. Sanity check that the deferral flag is set.
        assert b_widget._defer_body is True


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_last_sibling_completion_reveals_all_held_bodies() -> None:
    """When the last in-flight tool finishes, every deferred body mounts at once."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-A")
        _push_tool_start(screen, "tc-B")
        await pilot.pause()

        _push_tool_complete_with_content(screen, "tc-B", "B-result-payload")
        await pilot.pause()
        # Confirm B is held.
        b_widget = _widget_for(screen, "tc-B")
        assert "B-result-payload" not in _body_text(b_widget)

        # A completes — the LAST in-flight tool. SessionState notifies →
        # TranscriptWidget.refresh_from re-runs → B's defer_body flips
        # False → wholesale rebuild mounts B's content.
        _push_tool_complete_with_content(screen, "tc-A", "A-result-payload")
        await pilot.pause()

        b_widget = _widget_for(screen, "tc-B")
        a_widget = _widget_for(screen, "tc-A")
        assert b_widget._defer_body is False
        assert a_widget._defer_body is False
        # Both bodies should now be mounted.
        assert "B-result-payload" in _body_text(b_widget)
        assert "A-result-payload" in _body_text(a_widget)
        # The ``empty-body`` class drives the header's bottom-padding —
        # leaving it stale after un-defer would clip the newly-revealed
        # body against the header. Both cards now have visible bodies,
        # so neither should carry the class.
        assert "empty-body" not in b_widget.classes
        assert "empty-body" not in a_widget.classes


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_solo_completion_does_not_defer_body() -> None:
    """A single completed tool with no in-flight peers mounts its body immediately."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-only")
        await pilot.pause()
        _push_tool_complete_with_content(screen, "tc-only", "only-result-payload")
        await pilot.pause()
        widget = _widget_for(screen, "tc-only")
        assert widget._defer_body is False
        assert "only-result-payload" in _body_text(widget)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_in_flight_call_view_held_while_sibling_running() -> None:
    """Custom-viewer call-view (input preview) is held while siblings run.

    Reproduces the `fetch_stocks` viewer pattern in the demo: a tool
    with a registered ``ToolCallView`` emits a body content block on
    ``ToolCallStart`` (the input "lookup ACME"). Under parallel
    execution that body should be held back too — every card must
    collapse to its single header line so one tool's call-view doesn't
    pull the eye off the in-flight set.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        # A is a plain in-flight tool (header only).
        _push_tool_start(screen, "tc-A")
        # B starts with a call-view body block — the input preview a
        # custom viewer (or the bash tool) emits at call time.
        _push_tool_start(screen, "tc-B", call_view_text="lookup ACME")
        await pilot.pause()

        a_widget = _widget_for(screen, "tc-A")
        b_widget = _widget_for(screen, "tc-B")
        # Both cards see a parallel sibling → both defer.
        assert a_widget._defer_body is True
        assert b_widget._defer_body is True
        # And critically, B's call-view body must NOT have mounted.
        assert "lookup ACME" not in _body_text(b_widget)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_last_in_flight_tool_does_not_reveal_call_view_early() -> None:
    """The last running tool of a parallel batch stays deferred.

    Reproduces the visible jank operators reported: with three
    parallel tools A/B/C running and A,B finishing while C is still
    in_progress, C must NOT suddenly mount its call-view body — the
    operator's eye should stay on the still-running C card showing
    only its single header line, not on a half-revealed body for the
    one tool that hasn't finished. The reveal is atomic: every body
    waits for the last batch member to reach terminal.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-A")
        _push_tool_start(screen, "tc-B")
        _push_tool_start(screen, "tc-C", call_view_text="lookup ACME")
        await pilot.pause()

        # All three started as a parallel batch — all tagged with the
        # same batch id.
        batch_ids = {
            screen._state._tool_calls_by_id[tcid].parallel_batch_id
            for tcid in ("tc-A", "tc-B", "tc-C")
        }
        assert batch_ids == {1}

        # A finishes (B and C still running). Everyone defers.
        _push_tool_complete_with_content(screen, "tc-A", "A-result-payload")
        await pilot.pause()
        assert _widget_for(screen, "tc-C")._defer_body is True

        # B finishes — only C is still in_progress. Under the old
        # ``has_other_active_tools`` predicate, C would now reveal
        # (no other in-flight sibling). With the batch-aware gate, C
        # stays deferred because C is itself an in_progress batch
        # member keeping the batch unresolved.
        _push_tool_complete_with_content(screen, "tc-B", "B-result-payload")
        await pilot.pause()
        c_widget = _widget_for(screen, "tc-C")
        assert c_widget._defer_body is True, (
            "C must remain deferred while it is the last in-flight tool of "
            "its batch — its call-view must not jut out past the still-held "
            "bodies of its now-terminal siblings A and B."
        )
        assert "lookup ACME" not in _body_text(c_widget)
        # A and B (terminal, tagged with the same batch id) are also
        # still held.
        assert _widget_for(screen, "tc-A")._defer_body is True
        assert _widget_for(screen, "tc-B")._defer_body is True

        # C finishes — batch fully resolved. All three reveal at once.
        # (C's call-view text is replaced by the result payload per
        # ACP protocol semantics — ``ToolCallProgress.content`` REPLACES
        # the content collection. That's a separate concern from the
        # deferral gate; we only verify the gate releases at the right
        # moment.)
        _push_tool_complete_with_content(screen, "tc-C", "C-result-payload")
        await pilot.pause()
        for tcid, payload in (
            ("tc-A", "A-result-payload"),
            ("tc-B", "B-result-payload"),
            ("tc-C", "C-result-payload"),
        ):
            widget = _widget_for(screen, tcid)
            assert widget._defer_body is False
            assert payload in _body_text(widget)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_solo_tool_after_completed_batch_shows_immediately() -> None:
    """A fresh solo tool starting after a parallel batch never defers.

    Sanity check that the sticky ``parallel_batch_id`` on old terminal
    tools doesn't bleed into a later solo tool's gating. The old batch
    is settled; the new tool is its own thing.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        # Two parallel tools — start, then both complete.
        _push_tool_start(screen, "tc-A")
        _push_tool_start(screen, "tc-B")
        await pilot.pause()
        _push_tool_complete_with_content(screen, "tc-A", "A-result")
        _push_tool_complete_with_content(screen, "tc-B", "B-result")
        await pilot.pause()
        # Batch is settled — both bodies revealed.
        assert "A-result" in _body_text(_widget_for(screen, "tc-A"))
        assert "B-result" in _body_text(_widget_for(screen, "tc-B"))

        # Now a brand-new solo tool starts with a call-view body.
        _push_tool_start(screen, "tc-solo", call_view_text="solo-call-view")
        await pilot.pause()

        # The solo tool's parallel_batch_id must stay None — no other
        # in-progress tool when it started.
        solo_state = screen._state._tool_calls_by_id["tc-solo"]
        assert solo_state.parallel_batch_id is None
        solo_widget = _widget_for(screen, "tc-solo")
        assert solo_widget._defer_body is False
        assert "solo-call-view" in _body_text(solo_widget)
        # And the old batch's bodies are NOT pulled back into deferral
        # by the solo tool's in_progress status (its parallel_batch_id
        # is None, so it isn't in any batch).
        assert "A-result" in _body_text(_widget_for(screen, "tc-A"))
        assert "B-result" in _body_text(_widget_for(screen, "tc-B"))


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_new_parallel_batch_does_not_re_defer_settled_earlier_batch() -> None:
    """Starting a fresh parallel batch must not pull settled batches back into deferral.

    Regression: the deferred-body gate used to sweep the whole session
    for any "parallel" tool still in_progress. With a sticky boolean
    flag, a later batch's in-flight members re-asserted the gate for
    every tool from any earlier batch, hiding their already-revealed
    bodies again. Scoping the gate by ``parallel_batch_id`` keeps
    settled batches settled.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)

        # Batch 1: A and B run in parallel, then both complete.
        _push_tool_start(screen, "tc-A")
        _push_tool_start(screen, "tc-B")
        await pilot.pause()
        _push_tool_complete_with_content(screen, "tc-A", "A-result-payload")
        _push_tool_complete_with_content(screen, "tc-B", "B-result-payload")
        await pilot.pause()
        assert "A-result-payload" in _body_text(_widget_for(screen, "tc-A"))
        assert "B-result-payload" in _body_text(_widget_for(screen, "tc-B"))

        # Batch 2: C and D start (a fresh parallel batch). The bug:
        # the gate sees C and D in_progress and "any batch member
        # in_progress" hits True, so A and B's _defer_body flips back
        # to True and the widget early-return leaves stale bodies.
        # Fixed: the gate is scoped to each tool's own batch id, so
        # A and B stay revealed.
        _push_tool_start(screen, "tc-C", call_view_text="C-call-view")
        _push_tool_start(screen, "tc-D", call_view_text="D-call-view")
        await pilot.pause()

        a_state = screen._state._tool_calls_by_id["tc-A"]
        b_state = screen._state._tool_calls_by_id["tc-B"]
        c_state = screen._state._tool_calls_by_id["tc-C"]
        d_state = screen._state._tool_calls_by_id["tc-D"]

        # Two distinct batches.
        assert a_state.parallel_batch_id == b_state.parallel_batch_id
        assert c_state.parallel_batch_id == d_state.parallel_batch_id
        assert a_state.parallel_batch_id != c_state.parallel_batch_id

        # A and B (terminal, settled batch) stay revealed.
        a_widget = _widget_for(screen, "tc-A")
        b_widget = _widget_for(screen, "tc-B")
        assert a_widget._defer_body is False, (
            "settled batch 1 must NOT be re-deferred by an unrelated "
            "batch 2 starting later"
        )
        assert b_widget._defer_body is False
        assert "A-result-payload" in _body_text(a_widget)
        assert "B-result-payload" in _body_text(b_widget)

        # C and D (active batch) stay deferred until their batch
        # resolves — same gate as batch 1's own in-flight phase.
        assert _widget_for(screen, "tc-C")._defer_body is True
        assert _widget_for(screen, "tc-D")._defer_body is True

        # Resolve batch 2.
        _push_tool_complete_with_content(screen, "tc-C", "C-result-payload")
        await pilot.pause()
        _push_tool_complete_with_content(screen, "tc-D", "D-result-payload")
        await pilot.pause()
        for tcid in ("tc-A", "tc-B", "tc-C", "tc-D"):
            assert _widget_for(screen, tcid)._defer_body is False


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_tool_joining_active_batch_inherits_existing_batch_id() -> None:
    """A new tool starting while a batch is in flight joins that batch.

    Catches a regression where a fresh batch id would be allocated
    whenever ``_tag_parallel_batch`` re-ran with a different set of
    eligible tools. The newcomer must inherit any existing id present
    among current eligible peers.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        # A and B start first — fresh batch id allocated.
        _push_tool_start(screen, "tc-A")
        _push_tool_start(screen, "tc-B")
        await pilot.pause()
        original_id = screen._state._tool_calls_by_id["tc-A"].parallel_batch_id
        assert original_id is not None
        assert screen._state._tool_calls_by_id["tc-B"].parallel_batch_id == original_id

        # C starts while A and B are still in flight — joins their batch.
        _push_tool_start(screen, "tc-C")
        await pilot.pause()
        assert (
            screen._state._tool_calls_by_id["tc-C"].parallel_batch_id == original_id
        ), "newcomer must inherit the existing batch id, not allocate a new one"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_defer_body_flip_after_mount_clears_stale_body() -> None:
    """A tool that mounts its call-view solo, then joins a batch, must hide it.

    Defensive case for the deferred-body gate transitioning False→True
    after a body was already mounted: tool starts solo with a call-view
    body (no batch yet → not deferred → body mounts), then a second
    tool arrives and forms a parallel batch. The first tool's
    ``_compute_defer_body`` flips True, ``update_state`` is called
    with ``defer_body=True``, and the widget must tear down the
    already-mounted body — not leave it visible against the deferred
    gate.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)

        # tc-A starts solo with a visible call-view body.
        _push_tool_start(screen, "tc-A", call_view_text="A-call-view")
        await pilot.pause()
        a_widget = _widget_for(screen, "tc-A")
        assert a_widget._defer_body is False
        assert "A-call-view" in _body_text(a_widget)

        # tc-B arrives → A and B form a parallel batch → defer kicks in.
        _push_tool_start(screen, "tc-B")
        await pilot.pause()
        a_widget = _widget_for(screen, "tc-A")
        assert a_widget._defer_body is True
        # Bug B: without the False→True teardown, "A-call-view" would
        # remain visible. With the fix, the mounted body is cleared.
        assert "A-call-view" not in _body_text(a_widget), (
            "defer-on transition must clear the previously-mounted body"
        )
