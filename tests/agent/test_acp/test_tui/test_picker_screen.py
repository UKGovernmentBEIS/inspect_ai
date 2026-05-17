"""Pilot tests for the picker screen — empty + populated + filtered.

Textual's ``App.run_test()`` driver is asyncio-only; the trio variants
are skipped via ``@skip_if_trio`` (same pattern as the ACP transport
tests, since ``acp.Connection`` is also asyncio-bound).
"""

from __future__ import annotations

import time

import pytest
from test_helpers.utils import skip_if_trio
from textual.widgets import DataTable, Input, Markdown, Static

from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.picker_screen import PickerScreen
from inspect_ai.agent._acp.tui.widgets._formatting import (
    format_running as _format_running,
)

from .conftest import make_fake_client


def replace_total_tokens(row: SessionRow, total_tokens: int) -> SessionRow:
    """Helper: SessionRow is frozen, so build a copy with bumped tokens."""
    return SessionRow(
        eval_id=row.eval_id,
        session_id=row.session_id,
        task=row.task,
        sample_id=row.sample_id,
        epoch=row.epoch,
        agent_name=row.agent_name,
        started_at=row.started_at,
        target=row.target,
        total_tokens=total_tokens,
    )


def test_format_running_seconds() -> None:
    assert _format_running(1000.0, now=1012.0) == "12s"


def test_format_running_minutes_seconds() -> None:
    assert _format_running(1000.0, now=1000.0 + 65) == "1m 05s"


def test_format_running_hours_minutes() -> None:
    assert _format_running(1000.0, now=1000.0 + 3700) == "1h 01m"


def test_format_running_none() -> None:
    assert _format_running(None) == "—"


def test_format_running_negative_clamps_to_zero() -> None:
    """Clock skew between server and client can make ``now < started_at``."""
    assert _format_running(2000.0, now=1000.0) == "0s"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_empty_state_no_server(
    sample_rows: list[SessionRow],
) -> None:
    """No discovered evals + no --server → empty-state with the bootstrap hint."""
    client = make_fake_client([])
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PickerScreen)
        # No DataTable in the empty branch.
        with pytest.raises(Exception):
            screen.query_one(DataTable)
        # Heading is a Static; the multi-paragraph hint is a Markdown
        # widget (so the code blocks render with bash syntax
        # highlighting). The Markdown source is the source-of-truth
        # for the assertion — what gets rendered is derived from it.
        heading_text = str(screen.query_one(".heading", Static).content)
        hint_md = screen.query_one(Markdown)._markdown
        assert "No running Inspect evals" in heading_text
        assert "inspect eval <task> --acp-server" in hint_md
        assert "0.0.0.0:4545" in hint_md
        # Code blocks use bash syntax highlighting.
        assert "```bash" in hint_md


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_empty_state_with_server() -> None:
    """--server but no sessions → different empty message (no bootstrap hint)."""
    client = make_fake_client([])
    app = InspectAcpApp(eval_id=None, server="/tmp/explicit.sock", client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PickerScreen)
        heading_text = str(screen.query_one(".heading", Static).content)
        hint_md = screen.query_one(Markdown)._markdown
        assert "/tmp/explicit.sock" in heading_text
        assert "first turn begins" in hint_md
        # The bootstrap "inspect eval" hint is suppressed because the
        # user has explicitly pointed at a server.
        assert "inspect eval" not in hint_md


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_populated_renders_all_rows(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PickerScreen)
        table = screen.query_one(DataTable)
        assert table.row_count == 3
        # Six columns — the ▸ selection glyph used to live in a
        # dedicated 1-char gutter column but is now embedded into the
        # sample cell so DataTable's uniform cell_padding doesn't
        # produce a double-space gap. eval column is intentionally
        # absent — eval id lives on the SessionScreen meta row.
        columns = [str(c.label) for c in table.columns.values()]
        assert columns == [
            "sample",
            "task",
            "epoch",
            "agent",
            "tokens",
            "running",
        ]
        # Status text above the table includes the count summary.
        status = screen.query_one("#picker-status", Static)
        status_text = str(status.content)
        assert "Choose a running sample" in status_text
        assert "3 samples" in status_text
        assert "2 evals" in status_text
        # Agent values render — missing names become an em-dash so
        # the column never shows a literal "None". Agent column index
        # shifted by one with the gutter column removed (sample=0,
        # task=1, epoch=2, agent=3, tokens=4, running=5).
        agent_cells = [str(c) for c in table.get_column_at(3)]
        assert "react" in agent_cells
        assert "deepagent" in agent_cells


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_cursor_glyph_follows_cursor(
    sample_rows: list[SessionRow],
) -> None:
    """The ▸ glyph prefixing the sample cell tracks the cursor row.

    Pinned because the glyph swap is screen-level (not DataTable
    native) — implemented by hooking ``on_data_table_row_highlighted``.
    A regression that removes the hook would visually break the
    selection indicator the mockup relies on.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)

        # Sample column is index 0 now; cursor prefix is in the
        # cell's leading characters.
        sample_cells = [str(c) for c in table.get_column_at(0)]
        assert sample_cells[0].startswith("▸ ")
        assert all(not c.startswith("▸") for c in sample_cells[1:])

        # Move cursor down by one row and re-check.
        table.move_cursor(row=1)
        # The highlight event fires asynchronously; pump the loop.
        await pilot.pause()

        sample_cells = [str(c) for c in table.get_column_at(0)]
        assert sample_cells[1].startswith("▸ ")
        assert not sample_cells[0].startswith("▸")


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_running_column_ticks_in_place(monkeypatch) -> None:
    """The running column refreshes via PickerScreen._tick_running.

    Pin that the tick actually mutates the visible cell value (not
    just that the code path runs). Regression guard for the earlier
    bug where ``self._running_col_key = str(ColumnKey)`` produced an
    object repr instead of the literal "running" key, so every
    ``update_cell`` raised CellDoesNotExist and the broad except
    swallowed it silently — the tick "worked" but updated nothing.

    Build rows with ``started_at`` close to real-now so a small "+95s"
    jump crosses the visible-format boundary (``Ns`` → ``Nm XXs``).
    The fixture-supplied rows use 2023 wall-clock timestamps, which
    render as huge ``Xh XXm`` strings where a 95s jump is invisible.
    """
    from pathlib import Path

    from inspect_ai.agent._acp.discovery import TargetAddress

    now_for_fixture = time.time()
    rows = [
        SessionRow(
            eval_id="eval-x",
            session_id="sx-1",
            task="t",
            sample_id="0",
            epoch=1,
            agent_name="react",
            started_at=now_for_fixture - 5,
            target=TargetAddress(socket_path=Path("/tmp/x.sock")),
        )
    ]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)

        # ``running`` is column index 5 (sample, task, epoch, agent,
        # tokens, running) — the gutter column was removed and the
        # cursor glyph embedded into the sample cell instead.
        before = str(list(table.get_column_at(5))[0])
        assert before.endswith("s") and "m" not in before  # initial "Ns" form

        # Patch ``time.time`` on the *picker* module so its
        # ``_format_running`` sees a jumped clock. Patching the test
        # module's ``time`` doesn't propagate because both modules
        # reference the same module object, but monkeypatch's
        # ``setattr(time, ...)`` is the canonical way; we do it
        # against the shared module to be safe.
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + 95)
        picker._tick_running()
        await pilot.pause()

        after = str(list(table.get_column_at(5))[0])
        # Cursor / row count survive the in-place update.
        assert table.row_count == 1
        assert table.cursor_row == 0
        # Value actually changed — pins the fix.
        assert after != before
        assert "m " in after  # crossed into "Nm Ss" form after the jump


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_rescan_replaces_rows_when_set_changes(
    sample_rows: list[SessionRow],
) -> None:
    """The 10s rescan picks up new rows and removes finished ones.

    Drives the picker's ``_do_rescan`` directly rather than waiting
    for the real interval, then confirms the picker reflects the new
    row set after recompose. Also pins the "no-op when nothing
    changed" branch — a second call with the same row set must not
    rebuild the table.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        assert picker.query_one(DataTable).row_count == 3

        # Swap the fake client's row set to a different shape so the
        # next _do_rescan returns new data. Rescan goes via the App's
        # _enumerate, which calls _client.enumerate_sessions — the
        # fake honors whatever rows it was constructed with, so
        # rebind the App's _client to a fresh fake.
        new_rows = sample_rows[:1]  # only the first row remains
        app._client = make_fake_client(new_rows)
        await picker._do_rescan()
        await pilot.pause()
        # Picker should have recomposed to the smaller row set.
        assert picker._rows == new_rows
        assert picker.query_one(DataTable).row_count == 1

        # Calling again with the same row set is a no-op — same rows
        # already; no exception, no recompose churn.
        await picker._do_rescan()
        await pilot.pause()
        assert picker.query_one(DataTable).row_count == 1


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_eval_id_filter_narrows_rows(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id="eval-bbb", server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 1


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_row_select_attaches_session(
    sample_rows: list[SessionRow],
) -> None:
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        # Drive the picker via its on_select callback directly —
        # DataTable.RowSelected dispatch under Pilot is racy across
        # textual versions; the callback is the contract we care about.
        picker._on_select(sample_rows[0])
        # Worker spawns attach_session; wait for the screen swap.
        for _ in range(20):
            await pilot.pause()
            if app.screen is not picker:
                break
        from inspect_ai.agent._acp.tui.session_screen import SessionScreen

        assert isinstance(app.screen, SessionScreen)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_filter_input_hidden_by_default(
    sample_rows: list[SessionRow],
) -> None:
    """The filter Input is in the tree but hidden until ``/`` reveals it."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        inp = picker.query_one("#filter-input", Input)
        assert inp.has_class("hidden")


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_slash_reveals_filter_and_typing_narrows(
    sample_rows: list[SessionRow],
) -> None:
    """``/`` reveals the filter Input; typing live-filters the visible rows."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        assert table.row_count == 3

        # Drive the slash binding directly — pilot key dispatch for
        # "slash" is brittle across textual versions, and the binding
        # → action wiring is what we actually need to pin.
        picker.action_filter()
        await pilot.pause()
        inp = picker.query_one("#filter-input", Input)
        assert not inp.has_class("hidden")
        assert inp.has_focus

        # Drive the live filter by setting the value (avoids pilot key
        # racing) — the Input.Changed handler is what we want to pin.
        inp.value = "deep"
        await pilot.pause()
        # Only the "deepagent" row should remain.
        assert table.row_count == 1
        assert picker._visible_rows[0].agent_name == "deepagent"

        # Widen the filter — "task" matches both my_task and other_task.
        inp.value = "task"
        await pilot.pause()
        assert table.row_count == 3


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_escape_clears_and_hides_filter(
    sample_rows: list[SessionRow],
) -> None:
    """Esc clears the filter, hides the Input, and refocuses the table."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        inp = picker.query_one("#filter-input", Input)
        picker.action_filter()
        await pilot.pause()
        inp.value = "deep"
        await pilot.pause()
        assert picker.query_one(DataTable).row_count == 1

        picker.action_cancel_filter()
        await pilot.pause()
        assert inp.has_class("hidden")
        assert inp.value == ""
        assert picker._filter_text == ""
        assert picker.query_one(DataTable).row_count == 3


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_filter_survives_rescan(
    sample_rows: list[SessionRow],
) -> None:
    """A rescan that arrives while filtering reapplies the filter to new rows."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        inp = picker.query_one("#filter-input", Input)
        picker.action_filter()
        await pilot.pause()
        inp.value = "deep"
        await pilot.pause()
        assert picker.query_one(DataTable).row_count == 1

        # Rebind the client to a different row set and trigger a rescan.
        # The "deepagent" row is still present, so the post-rescan
        # filtered view should still show exactly that one row.
        app._client = make_fake_client(sample_rows[1:])  # drop sess-1
        await picker._do_rescan()
        await pilot.pause()
        # Source-of-truth shrinks, but the filter still narrows to deep.
        assert picker._rows == sample_rows[1:]
        assert picker.query_one(DataTable).row_count == 1
        assert picker._visible_rows[0].agent_name == "deepagent"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_action_attach_selects_visible_row(
    sample_rows: list[SessionRow],
) -> None:
    """``Enter`` (action_attach) picks the row under the cursor.

    Pinned because the Screen-level ``enter`` binding uses
    ``priority=True`` to win over DataTable's hidden enter binding —
    without the priority promotion, the ``↵ attach`` footer hint is
    shadowed and Enter doesn't go through ``action_attach``.
    """
    captured: list[SessionRow] = []
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        # Replace the App-supplied callback with a probe so we can
        # observe the selection without triggering attach plumbing.
        picker._on_select = captured.append

        table = picker.query_one(DataTable)
        table.move_cursor(row=1)
        await pilot.pause()
        picker.action_attach()
        assert captured == [sample_rows[1]]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_rescan_updates_tokens_in_steady_state(
    sample_rows: list[SessionRow],
) -> None:
    """Steady-state rescans must update the visible ``tokens`` cells in place.

    Pinned because the original ``_do_rescan`` short-circuited as soon
    as the id set matched, dropping fresh per-row fields on the floor.
    With ``total_tokens`` it meant the column stayed at the initial
    value for the whole picker session.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Tokens column is index 4 (sample=0, task=1, epoch=2,
        # agent=3, tokens=4, running=5) — gutter column was dropped.
        # Initial fixture rows have total_tokens=0 → cell renders "0".
        before = [str(c) for c in table.get_column_at(4)]
        assert all(c == "0" for c in before)

        # Rebind the client with the SAME session ids but bumped
        # token totals — exercises the "steady state" branch of
        # _do_rescan that previously returned early.
        bumped = [
            replace_total_tokens(sample_rows[0], 1_234),
            replace_total_tokens(sample_rows[1], 999_999),
            replace_total_tokens(sample_rows[2], 2_500_000),
        ]
        app._client = make_fake_client(bumped)
        await picker._do_rescan()
        await pilot.pause()

        after = [str(c) for c in table.get_column_at(4)]
        # _format_tokens: 1234 → "1.2K", 999999 → "1000K" → actually
        # under 1M so "1000K"? Let's compute: 999999/1000 = 999.999
        # → 1000 → trim ".0" → "1000K". And 2_500_000 → "2.5M".
        assert after[0] == "1.2K"
        assert after[1] == "1000K"
        assert after[2] == "2.5M"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_filter_typing_slash_appends_to_input(
    sample_rows: list[SessionRow],
) -> None:
    """When the filter Input has focus, ``/`` inserts a literal slash.

    The Screen-level ``slash`` binding has ``priority=True`` (so the
    footer hint stays visible). action_filter detects focus on the
    Input and inserts the character at the cursor rather than
    reopening the filter UI.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        inp = picker.query_one("#filter-input", Input)
        picker.action_filter()  # open + focus
        await pilot.pause()
        assert inp.has_focus
        inp.value = "ab"
        inp.cursor_position = 2
        # Now invoke the slash action directly — what the binding
        # would do when the user presses "/" with input focused.
        picker.action_filter()
        assert inp.value == "ab/"
        assert inp.cursor_position == 3
