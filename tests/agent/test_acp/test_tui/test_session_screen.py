"""Pilot tests for the bare SessionScreen (Phase 1).

Textual's ``App.run_test()`` driver is asyncio-only; trio variants
are skipped via ``@skip_if_trio``.

Every test in this module spins up a Textual app via ``run_test`` —
that's ~100ms of framework setup per test, which adds up during
iteration. The module-level ``pytestmark`` opts the file into the
``slow`` marker so these tests only run with ``--runslow``; pure unit
tests for the picker live in :mod:`test_picker_screen` (the fast
helper tests at the top of the file) and run on every collection.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio
from textual.widgets import Input, Static

from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.session_screen import SessionScreen

from .conftest import make_fake_client

pytestmark = pytest.mark.slow


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_meta_row_renders_all_fields(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Drive the row select directly.
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        meta = app.screen.query_one("#meta-text", Static)
        # ``meta.content`` returns the raw markup (with [dim]…[/dim]);
        # render the markup so assertions match what the user actually
        # sees on screen.
        text = meta.render_str(str(meta.content)).plain
        # ``inspect acp`` and ``eval-aaa`` are intentionally absent —
        # the window title carries the app name, and the eval id is
        # implicit from the picked session. Field labels precede each
        # value.
        assert "inspect acp" not in text
        assert "eval-aaa" not in text
        assert "task: my_task" in text
        assert "sample: 0" in text
        assert "epoch 1" in text
        assert "agent: react" in text


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_meta_row_handles_missing_agent_name(
    sample_rows: list[SessionRow],
) -> None:
    """Older evals (or solver-less configs) leave agent_name unset."""
    rows = [
        SessionRow(
            eval_id=sample_rows[0].eval_id,
            session_id=sample_rows[0].session_id,
            task=sample_rows[0].task,
            sample_id=sample_rows[0].sample_id,
            epoch=sample_rows[0].epoch,
            agent_name=None,  # the case under test
            started_at=sample_rows[0].started_at,
            target=sample_rows[0].target,
        )
    ]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        meta = app.screen.query_one("#meta-text", Static)
        # Em-dash placeholder rather than a literal "None".
        text = meta.render_str(str(meta.content)).plain
        assert "agent: —" in text


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_starts_with_connected_indicator(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        indicator = app.screen.query_one("#conn-indicator", Static)
        assert "connected" in str(indicator.content)
        assert indicator.has_class("up")


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_switch_sample_returns_to_picker(
    sample_rows: list[SessionRow],
) -> None:
    """^S on the session screen disconnects and returns to the picker.

    Also pins the no-toast invariant: the user-initiated path must not
    surface the "disconnected from server" warning the watcher fires
    on peer-side EOF.
    """
    from inspect_ai.agent._acp.tui.picker_screen import PickerScreen

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    notifications: list[tuple[str, str | None]] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)

        # Capture any notify() calls so we can assert the toast doesn't
        # fire on the user-initiated path.
        original_notify = app.notify

        def _capture(
            message: str,
            *,
            title: str = "",
            severity: str | None = None,
            **kwargs: object,
        ) -> None:
            notifications.append((message, severity))
            original_notify(
                message, title=title, severity=severity or "information", **kwargs
            )  # type: ignore[arg-type]

        app.notify = _capture  # type: ignore[method-assign]

        app.screen.action_switch_sample()
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, PickerScreen):
                break
        assert isinstance(app.screen, PickerScreen)
        assert app._attached is None  # type: ignore[attr-defined]
        # No "disconnected from server" toast — the user knows they
        # asked to switch.
        assert not any("disconnected" in msg.lower() for msg, _ in notifications), (
            notifications
        )


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_binds_ctrl_s_to_switch_sample(
    sample_rows: list[SessionRow],
) -> None:
    """The ^S binding must exist on SessionScreen with the right action."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        matched = [
            b for b in SessionScreen.BINDINGS if getattr(b, "key", None) == "ctrl+s"
        ]
        assert matched, "expected a ctrl+s binding on SessionScreen"
        assert matched[0].action == "switch_sample"
        # show=True so the Footer hint surfaces.
        assert matched[0].show is True


@skip_if_trio
@pytest.mark.anyio
async def test_session_screen_binds_enter_and_escape(
    sample_rows: list[SessionRow],
) -> None:
    """↵ submit / Esc interrupt must appear in the Footer keymap."""
    by_key = {b.key: b for b in SessionScreen.BINDINGS}
    assert "enter" in by_key
    assert by_key["enter"].action == "submit"
    assert by_key["enter"].show is True
    assert by_key["enter"].priority is True
    assert "escape" in by_key
    assert by_key["escape"].action == "interrupt"
    assert by_key["escape"].show is True
    assert by_key["escape"].priority is True


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_sends_prompt_and_clears_composer(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", Input)
        # Composer must be enabled — Phase 3 makes it interactive.
        assert composer.disabled is False
        composer.value = "  please continue  "
        await app.screen.action_submit()
        await pilot.pause()
        conn = app.screen._session.connection  # type: ignore[attr-defined]
        assert conn.requests == [
            (
                "session/prompt",
                {
                    "sessionId": sample_rows[0].session_id,
                    "prompt": [{"type": "text", "text": "please continue"}],
                },
            )
        ]
        assert composer.value == ""


@skip_if_trio
@pytest.mark.anyio
async def test_action_submit_with_empty_composer_is_noop(
    sample_rows: list[SessionRow],
) -> None:
    """Empty / whitespace-only composer must not fire a request."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", Input)
        composer.value = "   "
        await app.screen.action_submit()
        await pilot.pause()
        conn = app.screen._session.connection  # type: ignore[attr-defined]
        assert conn.requests == []


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_clears_draft_when_composer_nonempty(
    sample_rows: list[SessionRow],
) -> None:
    """Esc with text present clears the draft and does NOT cancel."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", Input)
        composer.value = "draft text"
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = app.screen._session.connection  # type: ignore[attr-defined]
        assert conn.notifications == []
        assert composer.value == ""


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_sends_cancel_when_agent_working(
    sample_rows: list[SessionRow],
) -> None:
    """Esc with no draft sends ``session/cancel`` only when the agent is working.

    Putting the SessionState's status into ``GENERATING`` by adding a
    pending message id mimics what happens when the server has signalled
    a model invocation start without a completion marker yet.
    """
    from inspect_ai.agent._acp.tui.state import StatusState

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", Input)
        composer.value = ""
        # Force the status into GENERATING by injecting a pending
        # message id — the property reads from this set first.
        app.screen.state._pending_message_ids.add("pending-msg")
        assert app.screen.state.status == StatusState.GENERATING
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = app.screen._session.connection  # type: ignore[attr-defined]
        assert conn.notifications == [
            (
                "session/cancel",
                {"sessionId": sample_rows[0].session_id},
            )
        ]
        # Optimistic local clear must have fired so the pill stops
        # advertising GENERATING during the server's cancel propagation.
        assert app.screen.state.status == StatusState.AWAITING_INPUT
        assert app.screen.state._pending_message_ids == set()


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_is_noop_when_awaiting_input(
    sample_rows: list[SessionRow],
) -> None:
    """Esc with no draft AND no in-flight work must NOT fire a cancel.

    The server's ``cancel_current_turn`` writes a ``between_turns``
    ``InterruptEvent`` to the transcript when there's nothing to
    cancel — a stray Esc here would otherwise pollute the log and
    flip interrupt state pending.
    """
    from inspect_ai.agent._acp.tui.state import StatusState

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", Input)
        composer.value = ""
        assert app.screen.state.status == StatusState.AWAITING_INPUT
        await app.screen.action_interrupt()
        await pilot.pause()
        conn = app.screen._session.connection  # type: ignore[attr-defined]
        assert conn.notifications == []


@skip_if_trio
@pytest.mark.anyio
async def test_action_interrupt_is_noop_during_quiescence_tail(
    sample_rows: list[SessionRow],
) -> None:
    """Esc must NOT cancel during the post-chunk quiescence window.

    Repro: a normal assistant chunk just arrived (so ``_last_chunk_at``
    is set, ``status`` reports GENERATING via the quiescence branch)
    but generation is actually finished — ``_pending_message_ids`` is
    empty and no tools are in flight. A stray Esc here would have hit
    the wire and made the server record a ``between_turns``
    InterruptEvent for the 2-second tail. The interrupt gate uses
    ``has_active_work`` instead of display status to avoid this.
    """
    from inspect_ai.agent._acp.tui.state import StatusState

    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
        assert isinstance(app.screen, SessionScreen)
        composer = app.screen.query_one("#composer", Input)
        composer.value = ""
        # Simulate the quiescence-tail state directly: chunk activity
        # within the quiescence window, but no pending event and no
        # tools in flight.
        app.screen.state._last_chunk_at = app.screen.state._now()
        assert app.screen.state.status == StatusState.GENERATING
        assert app.screen.state.has_active_work is False

        await app.screen.action_interrupt()
        await pilot.pause()
        conn = app.screen._session.connection  # type: ignore[attr-defined]
        assert conn.notifications == []
