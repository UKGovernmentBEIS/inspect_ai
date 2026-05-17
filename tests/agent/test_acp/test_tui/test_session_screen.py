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
from textual.widgets import Static

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
