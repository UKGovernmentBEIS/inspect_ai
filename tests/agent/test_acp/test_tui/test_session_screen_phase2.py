"""Pilot integration tests for Phase 2 SessionScreen wiring.

Drives the screen end-to-end via a SessionState the test owns: feeds
synthetic ACP notifications, asserts the meta + status + transcript
sub-surfaces all update from the same notification path that
production code uses (the App's ``attach_session(..., on_session_update=
state.consume)`` wiring).
"""

from __future__ import annotations

from typing import Any

import pytest
from acp.schema import (
    AgentMessageChunk,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
)
from test_helpers.utils import skip_if_trio
from textual.widgets import Static

from inspect_ai.agent._acp._tui._app import InspectAcpApp
from inspect_ai.agent._acp._tui._client import SessionRow
from inspect_ai.agent._acp._tui._session_screen import SessionScreen
from inspect_ai.agent._acp._tui._state import SessionState, StatusState
from inspect_ai.agent._acp._tui._widgets import (
    MessageWidget,
    SessionHeaderWidget,
    ToolCallWidget,
    TranscriptWidget,
)

from .conftest import make_fake_client

pytestmark = pytest.mark.slow


def _agent_chunk(text: str, *, message_id: str = "m1") -> SessionNotification:
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={"inspect.model": "phase2/model"},
    )
    return SessionNotification(session_id="sid", update=chunk)


def _tool_start(tcid: str = "tc1") -> SessionNotification:
    start = ToolCallStart(
        session_update="tool_call",
        tool_call_id=tcid,
        title="bash ls",
        status="in_progress",
        kind="other",
    )
    return SessionNotification(session_id="sid", update=start)


def _tool_complete(tcid: str = "tc1") -> SessionNotification:
    prog = ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id=tcid,
        status="completed",
    )
    return SessionNotification(session_id="sid", update=prog)


def _usage(used: int, size: int) -> SessionNotification:
    upd = UsageUpdate(session_update="usage_update", used=used, size=size)
    return SessionNotification(session_id="sid", update=upd)


async def _open_session_screen(
    app: InspectAcpApp, pilot: Any, row: SessionRow
) -> SessionScreen:
    app.screen._on_select(row)  # type: ignore[attr-defined]
    for _ in range(30):
        await pilot.pause()
        if isinstance(app.screen, SessionScreen):
            return app.screen
    raise AssertionError("SessionScreen did not mount")


@skip_if_trio
@pytest.mark.anyio
async def test_app_passes_on_session_update_to_attach(
    sample_rows: list[SessionRow],
) -> None:
    """Reviewer P2: the app must wire ``on_session_update`` through attach.

    Previously the app caught ``TypeError`` and retried without the
    kwarg, which silently produced a Phase 2 screen wired to a state
    object that never received notifications. The fake client now
    accepts the kwarg; this test asserts the app passes it.
    """
    client = make_fake_client(sample_rows)
    seen: dict[str, dict[str, Any]] = {}
    original_attach = client.attach_session

    async def _spy_attach(row: SessionRow, **kwargs: Any) -> Any:
        seen["kwargs"] = kwargs
        return await original_attach(row, **kwargs)

    client.attach_session = _spy_attach
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_session_screen(app, pilot, sample_rows[0])
        kwargs = seen.get("kwargs", {})
        assert "on_session_update" in kwargs
        # And that callback should be the SessionState's consume — a
        # callable, not a no-op default.
        assert callable(kwargs["on_session_update"])


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_in_flight_tool_reaches_transcript(
    sample_rows: list[SessionRow],
) -> None:
    """A ToolCallStart consumed by the screen's state mounts a tool widget.

    Replaces the old status-row pill assertion (the status row is
    gone — tokens moved up to the header, generating/calling-tools
    state is no longer rendered).
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = await _open_session_screen(app, pilot, sample_rows[0])
        screen.state.consume(_tool_start())
        await pilot.pause()
        tr = screen.query_one(TranscriptWidget)
        assert any(isinstance(c, ToolCallWidget) for c in tr.children)


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_renders_message_and_tool_call(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = await _open_session_screen(app, pilot, sample_rows[0])
        # An assistant chunk + a completed tool call should both
        # appear in the transcript in arrival order.
        screen.state.consume(_agent_chunk("hello world"))
        screen.state.consume(_tool_start("tc1"))
        screen.state.consume(_tool_complete("tc1"))
        await pilot.pause()
        tr = screen.query_one(TranscriptWidget)
        children = list(tr.children)
        assert any(isinstance(c, MessageWidget) for c in children)
        assert any(isinstance(c, ToolCallWidget) for c in children)
        # The completed tool should carry the completed class.
        tool_widget = next(c for c in children if isinstance(c, ToolCallWidget))
        assert tool_widget.has_class("completed")


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_token_chip_updates_on_usage_notification(
    sample_rows: list[SessionRow],
) -> None:
    """UsageUpdate flows from state → header meta row.

    Tokens moved up to the header (dim ``tokens`` label + bright
    value, alongside task / sample / etc.) when the status row was
    removed.
    """
    from rich.text import Text

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = await _open_session_screen(app, pilot, sample_rows[0])
        screen.state.consume(_usage(used=2_500, size=200_000))
        await pilot.pause()
        meta = screen.query_one(SessionHeaderWidget).query_one("#meta-text", Static)
        text = Text.from_markup(str(meta.content)).plain
        # 2_500 → "2.5K"; context-window denominator deliberately dropped.
        assert "tokens 2.5K" in text


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_state_falls_back_to_awaiting_after_quiescence(
    sample_rows: list[SessionRow],
) -> None:
    """Time-driven GENERATING → AWAITING_INPUT transition still derives.

    The status row is gone, but the state machine is still authoritative
    for the assistant chip's spinner gating (Phase 3+ will surface it
    again via composer state). This test pins the underlying state
    transition so future regressions are caught even without a visible
    pill.
    """
    fake_now = [1_000.0]

    def _now() -> float:
        return fake_now[0]

    state = SessionState(now=_now)
    # Chunk at t=1000 → GENERATING.
    state.consume(_agent_chunk("hello"))
    assert state.status == StatusState.GENERATING
    # Advance the fake clock past the 2s quiescence window. Bind via
    # a fresh local so mypy doesn't carry the GENERATING narrowing
    # from the earlier assert into this comparison.
    fake_now[0] = 1_005.0
    later: StatusState = state.status
    assert later == StatusState.AWAITING_INPUT
