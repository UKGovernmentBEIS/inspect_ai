"""Pilot tests for the queued-message ephemeral feedback.

Drives the full ``SessionScreen`` through ``action_submit`` and
``state.consume`` so the interaction between the optimistic enqueue,
the FIFO pop on chunk arrival, and the transcript-widget swap-in-place
all land together. Pure-function coverage for the state mutations +
chip rendering lives in :mod:`test_queued_messages` — keep this file
focused on cross-cutting integration.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from acp.schema import (
    SessionNotification,
    TextContentBlock,
    ToolCallStart,
    UserMessageChunk,
)
from test_helpers.utils import skip_if_trio
from textual.widgets import Input, Static

from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.session_screen import SessionScreen
from inspect_ai.agent._acp.tui.state import MessageGroup

from .conftest import make_fake_client

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_start(tool_call_id: str = "tc-1") -> SessionNotification:
    """A tool-in-flight notification.

    Drives ``lifecycle`` to ``"running"`` so ``action_submit`` follows
    the ephemeral path.
    """
    return SessionNotification(
        session_id="sid",
        update=ToolCallStart(
            session_update="tool_call",
            tool_call_id=tool_call_id,
            title="bash sleep 30",
            status="in_progress",
            raw_input={"command": "sleep 30"},
        ),
    )


def _operator_chunk(text: str, *, message_id: str = "srv-1") -> SessionNotification:
    return SessionNotification(
        session_id="sid",
        update=UserMessageChunk(
            session_update="user_message_chunk",
            content=TextContentBlock(type="text", text=text),
            message_id=message_id,
            field_meta={"inspect.user_source": "operator"},
        ),
    )


async def _open_session_screen(
    app: InspectAcpApp, pilot: Any, rows: list[SessionRow]
) -> SessionScreen:
    """Drive the picker → SessionScreen transition.

    Mirrors the pattern used by ``test_session_screen.py``'s other
    pilot tests.
    """
    await pilot.pause()
    app.screen._on_select(rows[0])  # type: ignore[attr-defined]
    for _ in range(20):
        await pilot.pause()
        if isinstance(app.screen, SessionScreen):
            break
    assert isinstance(app.screen, SessionScreen)
    return app.screen


def _queued(screen: SessionScreen) -> list[MessageGroup]:
    return [
        item
        for item in screen.state.items
        if isinstance(item, MessageGroup) and item.is_queued
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_send_during_running_appends_queued_ephemeral_and_clears_composer(
    sample_rows: list[SessionRow],
) -> None:
    """Send during ``running`` enqueues an ephemeral and clears the composer.

    Ephemeral appears in ``state.items`` immediately, the request is
    forwarded to the server, and the composer clears. The server hasn't
    yet drained the queue, so the real chunk has not arrived; the dim
    ``user · queued`` row is what the operator sees in the meantime.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(app, pilot, sample_rows)
        # Drive lifecycle into ``running`` via an in-flight tool.
        screen.state.consume(_tool_start())
        await pilot.pause()
        assert screen.state.lifecycle == "running"

        composer = screen.query_one("#composer", Input)
        composer.value = "please check /var/log"
        await screen.action_submit()
        await pilot.pause()

        # Composer was cleared on successful send.
        assert composer.value == ""
        # The request was forwarded to the server.
        conn = cast(Any, screen._session.connection)
        assert conn.requests == [
            (
                "session/prompt",
                {
                    "sessionId": sample_rows[0].session_id,
                    "prompt": [{"type": "text", "text": "please check /var/log"}],
                },
            )
        ]
        # And the ephemeral is now visible in state.items.
        queued = _queued(screen)
        assert len(queued) == 1
        assert queued[0].text == "please check /var/log"
        assert queued[0].user_source == "operator"


@skip_if_trio
@pytest.mark.anyio
async def test_send_during_idle_does_not_create_ephemeral(
    sample_rows: list[SessionRow],
) -> None:
    """Send during ``idle`` skips the optimistic ephemeral.

    The agent is parked in ``before_turn`` and the chunk usually
    round-trips within milliseconds, so an ephemeral would just flash.
    Skipping the optimistic echo on idle keeps the transcript steady
    on the common case.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(app, pilot, sample_rows)
        assert screen.state.lifecycle == "idle"

        composer = screen.query_one("#composer", Input)
        composer.value = "kick off"
        await screen.action_submit()
        await pilot.pause()

        # Request was sent, composer cleared, NO ephemeral mounted.
        assert composer.value == ""
        conn = cast(Any, screen._session.connection)
        assert len(conn.requests) == 1
        assert _queued(screen) == []


@skip_if_trio
@pytest.mark.anyio
async def test_arriving_operator_chunk_swaps_ephemeral_for_real_group(
    sample_rows: list[SessionRow],
) -> None:
    """Full round-trip: ephemeral appears on send, real chunk replaces it.

    The server's drained chunk pops the ephemeral and the real
    ``user · operator`` group renders in its place. Verified by the
    swap signature in ``state.items``: one queued entry → zero queued +
    one non-queued operator group with the same text.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(app, pilot, sample_rows)
        screen.state.consume(_tool_start())
        await pilot.pause()

        composer = screen.query_one("#composer", Input)
        composer.value = "please continue"
        await screen.action_submit()
        await pilot.pause()
        assert len(_queued(screen)) == 1

        # Server drains the queue and emits the chunk.
        screen.state.consume(_operator_chunk("please continue"))
        await pilot.pause()

        # Ephemeral is gone; a real operator user group replaces it.
        assert _queued(screen) == []
        real_groups = [
            item
            for item in screen.state.items
            if isinstance(item, MessageGroup) and not item.is_queued
        ]
        # Exactly one real user group with the operator source.
        operator_groups = [
            g for g in real_groups if g.role == "user" and g.user_source == "operator"
        ]
        assert len(operator_groups) == 1
        assert operator_groups[0].text == "please continue"


@skip_if_trio
@pytest.mark.anyio
async def test_send_failure_rolls_back_the_ephemeral(
    sample_rows: list[SessionRow],
) -> None:
    """Send failure rolls the ephemeral back and preserves the draft.

    ``send_request`` raised — the server never accepted the message,
    so the ephemeral must come back out and the composer keeps the
    operator's draft so they can retry (matches the pre-existing
    behaviour for any send failure).
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(app, pilot, sample_rows)
        screen.state.consume(_tool_start())
        await pilot.pause()

        async def _boom(_method: str, _params: dict[str, object]) -> None:
            raise RuntimeError("transport boom")

        screen._session.connection.send_request = _boom  # type: ignore[method-assign, assignment]

        composer = screen.query_one("#composer", Input)
        composer.value = "doomed message"
        await screen.action_submit()
        await pilot.pause()

        # Ephemeral was rolled back; composer text preserved so the
        # operator can edit and retry.
        assert _queued(screen) == []
        assert composer.value == "doomed message"


@skip_if_trio
@pytest.mark.anyio
async def test_multiple_sends_grow_a_single_ephemeral_and_drain_as_one(
    sample_rows: list[SessionRow],
) -> None:
    """Sends-while-busy append into one ephemeral; one chunk pops it.

    Mirrors server-side ``_coalesce_operator_messages``: N queued sends
    drain as ONE merged ``ChatMessageUser`` (paragraph-joined). The TUI
    keeps a single growing ephemeral so the visible row matches what
    the model will actually see. On the server's single merged chunk
    arrival, the ephemeral pops and the real merged group renders.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(app, pilot, sample_rows)
        screen.state.consume(_tool_start())
        await pilot.pause()

        composer = screen.query_one("#composer", Input)
        for text in ("first", "second", "third"):
            composer.value = text
            await screen.action_submit()
            await pilot.pause()
        # Single bucket — one queued row with paragraph-joined text.
        queued = _queued(screen)
        assert len(queued) == 1
        assert queued[0].text == "first\n\nsecond\n\nthird"

        # Server drains all three into one ChatMessageUser → one chunk.
        screen.state.consume(
            _operator_chunk("first\n\nsecond\n\nthird", message_id="srv-merged")
        )
        await pilot.pause()

        assert _queued(screen) == []
        # The merged operator message now sits in the transcript as one
        # real group (not three) — text matches the coalesced merge.
        operator_texts = [
            item.text
            for item in screen.state.items
            if isinstance(item, MessageGroup)
            and not item.is_queued
            and item.user_source == "operator"
        ]
        assert operator_texts == ["first\n\nsecond\n\nthird"]


@skip_if_trio
@pytest.mark.anyio
async def test_appending_to_queued_ephemeral_updates_mounted_widget_text(
    sample_rows: list[SessionRow],
) -> None:
    """Append-on-existing must update the rendered ``.queued-body`` in place.

    Regression for: state's ``segments[0].text`` grew to the joined
    text, but the mounted ``MessageWidget`` rendered a plain ``Static``
    for the queued body that ``_update_last_segment_widget`` didn't
    know how to update — the visible row stayed at the original text
    while state had moved on. Pinned by inspecting the actual rendered
    Static's content (``.renderable``), not just ``state.items[*].text``.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(app, pilot, sample_rows)
        screen.state.consume(_tool_start())
        await pilot.pause()

        composer = screen.query_one("#composer", Input)
        composer.value = "first"
        await screen.action_submit()
        await pilot.pause()
        composer.value = "second"
        await screen.action_submit()
        await pilot.pause()
        composer.value = "third"
        await screen.action_submit()
        await pilot.pause()

        # State has the merged text — already covered elsewhere; we
        # care about the rendered widget here.
        queued_bodies = [
            w for w in screen.query(Static).results() if "queued-body" in w.classes
        ]
        assert len(queued_bodies) == 1
        assert str(queued_bodies[0].content) == "first\n\nsecond\n\nthird"
