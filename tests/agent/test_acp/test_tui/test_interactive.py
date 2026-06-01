"""TUI behaviour for non-interactive (observe-only) sessions.

Observe-only sessions are real per-sample transports with no bound agent
turn loop. The TUI's only special handling is to hide the composer row
(there's nothing to prompt) — cancel-sample / cancel-tool controls stay
available, so it isn't a pure read-only state and gets no extra chrome.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import INTERACTIVE_META_KEY, PICKER_META_KEY
from inspect_ai.agent._acp.tui.client import (
    SessionRow,
    _refresh_row_from_binding_meta,
)


def _row(*, interactive: bool = True, session_id: str = "sess-1") -> SessionRow:
    return SessionRow(
        eval_id="eval-aaa",
        session_id=session_id,
        task="my_task",
        sample_id="0",
        epoch=1,
        agent_name="react",
        started_at=1_700_000_000.0,
        target=TargetAddress(socket_path=Path("/tmp/acp_test.sock")),
        interactive=interactive,
    )


def test_refresh_row_flips_interactive_from_outer_meta() -> None:
    """``inspect.interactive`` on the outer binding ``_meta`` updates the row."""
    session = SimpleNamespace(row=_row(interactive=True), session_id="sess-1")
    notification = SimpleNamespace(field_meta={INTERACTIVE_META_KEY: False})

    _refresh_row_from_binding_meta(session, notification)  # type: ignore[arg-type]

    assert session.row.interactive is False


def test_refresh_row_leaves_interactive_when_meta_absent() -> None:
    """No ``inspect.interactive`` key → the row's interactivity is untouched."""
    session = SimpleNamespace(row=_row(interactive=True), session_id="sess-1")
    notification = SimpleNamespace(field_meta={})

    _refresh_row_from_binding_meta(session, notification)  # type: ignore[arg-type]

    assert session.row.interactive is True


def test_refresh_row_interactive_independent_of_picker_entry() -> None:
    """Interactive flips from the OUTER meta even when no picker entry matches."""
    session = SimpleNamespace(row=_row(interactive=True), session_id="sess-1")
    notification = SimpleNamespace(
        field_meta={
            INTERACTIVE_META_KEY: False,
            # An entry for a DIFFERENT session — the failsOnError loop
            # skips it, but the outer interactive flag still applies.
            PICKER_META_KEY: [{"sessionId": "other", "failsOnError": False}],
        }
    )

    _refresh_row_from_binding_meta(session, notification)  # type: ignore[arg-type]

    assert session.row.interactive is False


class TestComposerVisibility:
    """Pilot-based: needs a running event loop + Textual app."""

    pytestmark = pytest.mark.slow

    async def _composer_row_hidden(self, interactive: bool) -> bool:
        from inspect_ai.agent._acp.tui.app import InspectAcpApp
        from inspect_ai.agent._acp.tui.session_screen import SessionScreen

        from .conftest import make_fake_client

        rows = [_row(interactive=interactive)]
        client = make_fake_client(rows)
        app = InspectAcpApp(eval_id=None, server=None, client=client)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen._on_select(rows[0])  # type: ignore[attr-defined]
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, SessionScreen):
                    break
            assert isinstance(app.screen, SessionScreen)
            composer_row = app.screen.query_one("#composer-row")
            return not composer_row.display

    @skip_if_trio
    @pytest.mark.anyio
    async def test_observe_only_session_hides_composer_row(self) -> None:
        assert await self._composer_row_hidden(interactive=False) is True

    @skip_if_trio
    @pytest.mark.anyio
    async def test_interactive_session_shows_composer_row(self) -> None:
        assert await self._composer_row_hidden(interactive=True) is False

    async def _check_actions(self, interactive: bool) -> dict[str, bool | None]:
        from inspect_ai.agent._acp.tui.app import InspectAcpApp
        from inspect_ai.agent._acp.tui.session_screen import SessionScreen

        from .conftest import make_fake_client

        rows = [_row(interactive=interactive)]
        client = make_fake_client(rows)
        app = InspectAcpApp(eval_id=None, server=None, client=client)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen._on_select(rows[0])  # type: ignore[attr-defined]
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, SessionScreen):
                    break
            assert isinstance(app.screen, SessionScreen)
            screen = app.screen
            return {
                action: screen.check_action(action, ())
                for action in ("submit", "newline", "interrupt")
            }

    @skip_if_trio
    @pytest.mark.anyio
    async def test_observe_only_hides_composer_command_footer_hints(self) -> None:
        """submit / newline / interrupt are gated off for observe-only."""
        actions = await self._check_actions(interactive=False)
        assert actions["submit"] is False
        assert actions["newline"] is False
        # No card mounted → interrupt is hidden too.
        assert actions["interrupt"] is False

    @skip_if_trio
    @pytest.mark.anyio
    async def test_interactive_keeps_composer_command_footer_hints(self) -> None:
        """submit / newline / interrupt stay available when interactive."""
        actions = await self._check_actions(interactive=True)
        assert actions["submit"] is True
        assert actions["newline"] is True
        assert actions["interrupt"] is True
