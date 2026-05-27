"""Pilot tests for the ``^L cancel tool`` keybind.

Exercises the SessionScreen dispatch path end-to-end against a fake
``Connection`` that records outbound JSON-RPC calls. Mirrors the
:file:`test_cancel_sample.py` pattern — bring up an App + SessionScreen
via the picker, simulate the operator action, assert
``inspect/cancel_tool_call`` lands on the wire with the right
``toolCallId``.

The cancel surface is the screen-level ``^L`` keybind only — there's
no per-card inline link, so no click-path coverage here. Pure-function
tests for the underlying state + footer composition live in
:file:`test_state.py` and :file:`test_tool_call_footer.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from acp.schema import SessionNotification, ToolCallStart
from test_helpers.utils import skip_if_trio
from textual.widgets import Static

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import INSPECT_CANCEL_TOOL_CALL_METHOD
from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.session_screen import SessionScreen
from inspect_ai.agent._acp.tui.widgets.tool_call import ToolCallWidget

from .conftest import make_fake_client


def _row() -> SessionRow:
    """Build a SessionRow for pilot tests."""
    return SessionRow(
        eval_id="eval-x",
        session_id="sid-x",
        task="t",
        sample_id="s1",
        epoch=1,
        agent_name="react",
        started_at=1_700_000_000.0,
        target=TargetAddress(socket_path=Path("/tmp/acp_cancel_tool_test.sock")),
        fails_on_error=False,
    )


async def _open_session_screen(pilot: Any, rows: list[SessionRow]) -> SessionScreen:
    """Walk PickerScreen → SessionScreen via the picker's ``_on_select``."""
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
    title: str = "bash sleep 30",
) -> None:
    """Inject a ToolCallStart notification into the screen's SessionState.

    Simulates the wire path without standing up a real server — the
    cancel-tool-call surface only cares about the resulting in-flight
    ``ToolCallState``, so this is the same shape the live router
    would deliver.
    """
    start = ToolCallStart(
        session_update="tool_call",
        tool_call_id=tool_call_id,
        title=title,
        status="in_progress",
        raw_input={"command": "sleep 30"},
    )
    screen._state.consume(SessionNotification(session_id="sid-x", update=start))


def _recorded_cancel_requests(screen: SessionScreen) -> list[dict[str, Any]]:
    """All ``inspect/cancel_tool_call`` params the fake connection captured."""
    requests = screen._session.connection.requests  # type: ignore[attr-defined]
    return [
        params
        for method, params in requests
        if method == INSPECT_CANCEL_TOOL_CALL_METHOD
    ]


# ---------------------------------------------------------------------------
# ^L keybind path
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_l_cancels_only_in_flight_tool() -> None:
    """With one tool in flight, ``^L`` fires cancel for that tool."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-1")
        await pilot.pause()

        await pilot.press("ctrl+l")
        # Allow the worker to fire the request.
        for _ in range(10):
            await pilot.pause()
            if _recorded_cancel_requests(screen):
                break

        cancels = _recorded_cancel_requests(screen)
        assert cancels == [{"sessionId": "sid-x", "toolCallId": "tc-1"}]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_l_cancels_all_in_flight_tools() -> None:
    """Two tools in flight: a single ``^L`` fans out to cancel both.

    Under parallel tool calls multiple tools share the in-flight state;
    one keystroke dispatches one ``inspect/cancel_tool_call`` RPC per
    tool, in ``start_time`` ascending order (oldest first).
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-older", title="bash sleep 30")
        _push_tool_start(screen, "tc-newer", title="bash sleep 60")
        await pilot.pause()

        assert screen._state.cancel_tool_call_ids == ["tc-older", "tc-newer"]

        await pilot.press("ctrl+l")
        for _ in range(20):
            await pilot.pause()
            if len(_recorded_cancel_requests(screen)) >= 2:
                break

        cancels = _recorded_cancel_requests(screen)
        assert cancels == [
            {"sessionId": "sid-x", "toolCallId": "tc-older"},
            {"sessionId": "sid-x", "toolCallId": "tc-newer"},
        ]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_l_is_noop_after_all_eligible_tools_cancelled() -> None:
    """A second ``^L`` after the fan-out finds nothing eligible.

    The first press marks every in-flight tool ``cancel_requested``;
    the accessor's filter then excludes them, so a follow-up press
    fires no additional requests.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-older")
        _push_tool_start(screen, "tc-newer")
        await pilot.pause()

        await pilot.press("ctrl+l")
        for _ in range(20):
            await pilot.pause()
            if len(_recorded_cancel_requests(screen)) >= 2:
                break

        await pilot.press("ctrl+l")
        for _ in range(5):
            await pilot.pause()

        assert _recorded_cancel_requests(screen) == [
            {"sessionId": "sid-x", "toolCallId": "tc-older"},
            {"sessionId": "sid-x", "toolCallId": "tc-newer"},
        ]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_l_is_noop_when_no_tools_in_flight() -> None:
    """Without an eligible tool, ``^L`` fires no request (check_action gate)."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        # No tool in flight — accessor returns None, binding is hidden
        # via check_action and a stray press is a no-op even if it
        # somehow fires.
        assert screen._state.cancel_tool_call_id is None

        await pilot.press("ctrl+l")
        for _ in range(5):
            await pilot.pause()

        assert _recorded_cancel_requests(screen) == []


# ---------------------------------------------------------------------------
# Post-dispatch visual feedback (cancelling…) + idempotence
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_card_header_flips_to_cancelling_after_dispatch() -> None:
    """Post-dispatch, the rendered header Static shows the dim ``cancelling…`` marker.

    Reads the mounted ``.header`` Static rather than calling
    ``_header_text()`` directly — verifies the
    ``mark_cancel_requested`` notification chains through the
    transcript fingerprint diff into ``update_state`` so the
    rendered text actually updates (not just the in-memory state).
    Without ``cancel_requested`` in the fingerprint, this assertion
    would only pass on the 0.5s tick, breaking the
    immediate-feedback contract.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-1")
        await pilot.pause()

        await pilot.press("ctrl+l")
        for _ in range(10):
            await pilot.pause()
            if screen._state._tool_calls_by_id["tc-1"].cancel_requested:
                break

        assert screen._state._tool_calls_by_id["tc-1"].cancel_requested is True
        widget = screen.query_one(ToolCallWidget)
        # Read the rendered Static, not the helper — checks the full
        # state-notify → fingerprint-diff → update_state chain.
        rendered = str(widget.query_one(".header", Static).content)
        assert "cancelling" in rendered


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_double_ctrl_l_fires_request_only_once_for_same_tool() -> None:
    """``^L`` mash on a single in-flight tool fires the request exactly once.

    First ^L sets ``cancel_requested = True`` and dispatches; the
    accessor then filters that tool out, so a second ^L with no other
    eligible tool finds ``cancel_tool_call_id is None`` and is a no-op.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-1")
        await pilot.pause()

        await pilot.press("ctrl+l")
        for _ in range(10):
            await pilot.pause()
            if _recorded_cancel_requests(screen):
                break

        # Second press — accessor is None now, so dispatcher no-ops.
        await pilot.press("ctrl+l")
        for _ in range(5):
            await pilot.pause()

        assert _recorded_cancel_requests(screen) == [
            {"sessionId": "sid-x", "toolCallId": "tc-1"}
        ]


# ---------------------------------------------------------------------------
# Clear-on-failure paths — the request didn't take effect, so the
# operator's intent should be revertable (footer normalises + ^L retargets).
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_cancel_request_exception_clears_cancel_requested() -> None:
    """RPC exception → ``cancel_requested`` cleared so ^L can retry."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-1")
        await pilot.pause()

        # Replace send_request with one that always raises.
        async def _boom(_method: str, _params: dict[str, object]) -> None:
            raise ConnectionError("simulated")

        screen._session.connection.send_request = _boom  # type: ignore[method-assign, assignment]

        await pilot.press("ctrl+l")
        # Wait for the worker to fire + the exception handler to clear.
        for _ in range(10):
            await pilot.pause()
            if not screen._state._tool_calls_by_id["tc-1"].cancel_requested:
                break

        # Flag cleared → ^L is re-targetable on the same tool.
        assert screen._state._tool_calls_by_id["tc-1"].cancel_requested is False
        assert screen._state.cancel_tool_call_id == "tc-1"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_cancel_response_false_clears_cancel_requested() -> None:
    """``{cancelled: false}`` → ``cancel_requested`` cleared (no retry stuck path).

    Per the server contract, ``cancelled: false`` includes the case
    where the pending tool had no ``_cancel_fn`` bound — the tool
    keeps running. Without clearing the flag, the footer would stay
    on ``cancelling…`` forever and ^L's eligibility filter would
    permanently hide the tool.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-1")
        await pilot.pause()

        # Replace send_request with one returning {cancelled: false}.
        async def _no_cancel(
            _method: str, _params: dict[str, object]
        ) -> dict[str, bool]:
            return {"cancelled": False}

        screen._session.connection.send_request = _no_cancel  # type: ignore[method-assign, assignment]

        await pilot.press("ctrl+l")
        for _ in range(10):
            await pilot.pause()
            if not screen._state._tool_calls_by_id["tc-1"].cancel_requested:
                break

        assert screen._state._tool_calls_by_id["tc-1"].cancel_requested is False
        # Eligibility restored — another ^L would target the same tool.
        assert screen._state.cancel_tool_call_id == "tc-1"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_cancel_response_true_keeps_cancel_requested() -> None:
    """``{cancelled: true}`` → flag stays set; awaiting failure event.

    The natural terminal-status event will land shortly and drive the
    card to ``failed``; the ``cancelling…`` marker drops on its own
    via the ``not is_terminal`` gate in ``_footer_text``.
    """
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        _push_tool_start(screen, "tc-1")
        await pilot.pause()

        async def _yes_cancel(
            _method: str, _params: dict[str, object]
        ) -> dict[str, bool]:
            return {"cancelled": True}

        screen._session.connection.send_request = _yes_cancel  # type: ignore[method-assign, assignment]

        await pilot.press("ctrl+l")
        for _ in range(10):
            await pilot.pause()
            # Give the worker a chance to complete + any spurious
            # clear to land if the logic regressed.

        assert screen._state._tool_calls_by_id["tc-1"].cancel_requested is True
