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

from inspect_ai.agent._acp._tui._app import InspectAcpApp
from inspect_ai.agent._acp._tui._client import SessionRow
from inspect_ai.agent._acp._tui._session_screen import SessionScreen

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
        text = str(meta.content)
        # Prefaces dropped for eval/task/sample/epoch — context makes
        # them obvious. ``agent:`` keeps its label so the value (e.g.
        # "react") is unambiguous.
        assert "inspect acp" in text
        assert "eval-aaa" in text
        assert "my_task" in text
        assert "0/1" in text  # sample_id/epoch
        assert "agent: react" in text
        # Make sure the dropped labels really aren't there.
        assert "eval eval-aaa" not in text
        assert "task my_task" not in text
        assert "epoch" not in text
        assert "sample 0" not in text


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
        assert "agent: —" in str(meta.content)


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
