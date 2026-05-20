"""Pilot tests for the picker screen — empty + populated + filtered.

Textual's ``App.run_test()`` driver is asyncio-only; the trio variants
are skipped via ``@skip_if_trio`` (same pattern as the ACP transport
tests, since ``acp.Connection`` is also asyncio-bound).
"""

from __future__ import annotations

import time

import pytest
from rich.text import Text
from test_helpers.utils import skip_if_trio
from textual.widgets import DataTable, Input, Markdown, Static

from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import SessionRow
from inspect_ai.agent._acp.tui.picker_screen import (
    PickerScreen,
    _display_task,
    _row_matches,
    _sort_rows,
)
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
            "epoch",
            "task",
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
        # the column never shows a literal "None". Column indices:
        # sample=0, epoch=1, task=2, agent=3, tokens=4, running=5.
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

        # ``running`` is column index 5 (sample, epoch, task, agent,
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
        # Compare as sets — _rows is now sorted longest-running-first
        # which differs from the fixture's source order.
        assert {r.session_id for r in picker._rows} == {
            r.session_id for r in sample_rows[1:]
        }
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
        # Tokens column is index 4 (sample=0, epoch=1, task=2,
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
        # Display order is longest-running-first now, so the fixture's
        # sess-3 (oldest started_at) lands at row 0, sess-2 at row 1,
        # sess-1 at row 2. _format_tokens: 1234 → "1.2K",
        # 999999/1000 = 999.999 → 1000 → trim ".0" → "1000K",
        # 2_500_000 → "2.5M". Bumped values map by session: sess-1=1.2K,
        # sess-2=1000K, sess-3=2.5M.
        assert after[0] == "2.5M"  # sess-3 (oldest)
        assert after[1] == "1000K"  # sess-2
        assert after[2] == "1.2K"  # sess-1 (newest)


def test_display_task_strips_namespace_prefix() -> None:
    """Single-slash split: everything before the first ``/`` is dropped."""
    assert _display_task("inspect_evals/swe_bench") == "swe_bench"
    assert _display_task("plain") == "plain"
    # Multi-segment paths keep everything after the first slash.
    assert _display_task("a/b/c") == "b/c"
    assert _display_task("") == ""
    # Leading slash leaves an empty namespace → return the tail.
    assert _display_task("/foo") == "foo"
    # Trailing slash leaves an empty tail → return the original.
    assert _display_task("namespace/") == "namespace"


def test_row_matches_filters_on_stripped_task(
    sample_rows: list[SessionRow],
) -> None:
    """Filter scope is the stripped task display form, not the full string."""
    # Build a row with a namespaced task so the stripping matters.
    row = SessionRow(
        eval_id=sample_rows[0].eval_id,
        session_id=sample_rows[0].session_id,
        task="inspect_evals/swe_bench",
        sample_id=sample_rows[0].sample_id,
        epoch=sample_rows[0].epoch,
        agent_name=sample_rows[0].agent_name,
        started_at=sample_rows[0].started_at,
        target=sample_rows[0].target,
    )
    assert _row_matches(row, "swe")  # stripped form matches
    # The hidden namespace deliberately does NOT match — operator can
    # only filter on what's on screen.
    assert not _row_matches(row, "inspect_evals")


def test_sort_rows_orders_by_started_at_ascending(
    sample_rows: list[SessionRow],
) -> None:
    """Smallest started_at (longest running) lands at index 0."""
    sorted_rows = _sort_rows(sample_rows)
    # Fixture: sess-3 has the oldest started_at, sess-2 next, sess-1 newest.
    assert [r.session_id for r in sorted_rows] == ["sess-3", "sess-2", "sess-1"]


def test_sort_rows_none_started_at_sinks_to_bottom(
    sample_rows: list[SessionRow],
) -> None:
    """Rows with started_at=None sort after every timestamped row."""
    pre_start = SessionRow(
        eval_id=sample_rows[0].eval_id,
        session_id="sess-pre",
        task="not_started_yet",
        sample_id="9",
        epoch=1,
        agent_name=None,
        started_at=None,
        target=sample_rows[0].target,
    )
    sorted_rows = _sort_rows([pre_start, *sample_rows])
    assert sorted_rows[-1].session_id == "sess-pre"


def test_sort_rows_deterministic_tiebreak(sample_rows: list[SessionRow]) -> None:
    """Identical started_at → tiebreak on (eval_id, sample_id, epoch)."""
    a = SessionRow(
        eval_id="eval-aaa",
        session_id="tie-a",
        task="t",
        sample_id="2",
        epoch=1,
        agent_name=None,
        started_at=1000.0,
        target=sample_rows[0].target,
    )
    b = SessionRow(
        eval_id="eval-aaa",
        session_id="tie-b",
        task="t",
        sample_id="1",
        epoch=1,
        agent_name=None,
        started_at=1000.0,
        target=sample_rows[0].target,
    )
    # Same started_at, b has smaller sample_id ⇒ b comes first.
    sorted_rows = _sort_rows([a, b])
    assert [r.session_id for r in sorted_rows] == ["tie-b", "tie-a"]
    # Re-shuffle the input; the output order is unchanged.
    sorted_again = _sort_rows([b, a])
    assert [r.session_id for r in sorted_again] == ["tie-b", "tie-a"]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_task_column_renders_stripped_name(
    sample_rows: list[SessionRow],
) -> None:
    """Namespaced task names render with the prefix stripped."""
    namespaced = SessionRow(
        eval_id=sample_rows[0].eval_id,
        session_id="sess-ns",
        task="inspect_evals/swe_bench",
        sample_id="0",
        epoch=1,
        agent_name="react",
        started_at=sample_rows[0].started_at,
        target=sample_rows[0].target,
    )
    client = make_fake_client([namespaced])
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Task column is index 2 (sample, epoch, task, agent, tokens, running).
        task_cells = [str(c) for c in table.get_column_at(2)]
        assert task_cells == ["swe_bench"]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_tokens_cell_and_header_are_right_justified(
    sample_rows: list[SessionRow],
) -> None:
    """Tokens column header + cells are wrapped in right-justified Text."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Header label is a Text("tokens", justify="right").
        tokens_col = list(table.columns.values())[4]
        assert isinstance(tokens_col.label, Text)
        assert tokens_col.label.justify == "right"
        # Every cell value is a Text(..., justify="right").
        tokens_cells = list(table.get_column_at(4))
        assert all(isinstance(c, Text) for c in tokens_cells)
        assert all(c.justify == "right" for c in tokens_cells)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_tokens_tick_preserves_right_justify(
    sample_rows: list[SessionRow],
) -> None:
    """``_tick_tokens`` keeps the right-justify wrap on updated cells.

    Regression guard for ``update_cell`` losing the alignment by passing
    a bare string. ``_tick_column`` MUST round-trip through
    ``_tokens_cell``.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)

        bumped = [
            replace_total_tokens(sample_rows[0], 1_234),
            replace_total_tokens(sample_rows[1], 2_345),
            replace_total_tokens(sample_rows[2], 3_456),
        ]
        app._client = make_fake_client(bumped)
        await picker._do_rescan()
        await pilot.pause()

        tokens_cells = list(table.get_column_at(4))
        assert all(isinstance(c, Text) for c in tokens_cells)
        assert all(c.justify == "right" for c in tokens_cells)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_rows_are_sorted_longest_running_first(
    sample_rows: list[SessionRow],
) -> None:
    """Display order = oldest started_at first regardless of input order."""
    # Reverse the fixture so input order is intentionally wrong.
    client = make_fake_client(list(reversed(sample_rows)))
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        # _rows is the sorted form; first row is the oldest started_at.
        assert picker._rows[0].session_id == "sess-3"
        assert picker._rows[-1].session_id == "sess-1"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_cursor_preserved_across_rescan_same_set(
    sample_rows: list[SessionRow],
) -> None:
    """Cursor stays on the same session across a steady-state rescan.

    Most common in-the-wild case: operator scrolls to a row, walks
    away for tea, comes back to find the cursor exactly where they
    left it.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Move cursor to row 2 (last row in sorted display order).
        table.move_cursor(row=2)
        await pilot.pause()
        cursor_session = picker._visible_rows[table.cursor_row].session_id

        # Drive a rescan with identical ids + bumped tokens (steady
        # state path).
        bumped = [replace_total_tokens(r, r.total_tokens + 100) for r in sample_rows]
        app._client = make_fake_client(bumped)
        await picker._do_rescan()
        await pilot.pause()

        # Cursor should still be on the same session.
        new_cursor_session = picker._visible_rows[table.cursor_row].session_id
        assert new_cursor_session == cursor_session


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_cursor_preserved_across_filter_typing(
    sample_rows: list[SessionRow],
) -> None:
    """Typing into the filter preserves the cursor if the session survives.

    Pinned because the prior behavior reset the cursor to row 0 on
    every keystroke — typing "react" while the cursor was on the
    only react row would yank it back to the top of the filtered
    list. Useless when navigating-while-filtering.
    """
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Move cursor onto the deepagent row (sess-3, sorted to index 0
        # because it's the oldest). Pick a row whose session_id is
        # uniquely matched by "deep" so the filter narrows to exactly
        # that row.
        for idx, r in enumerate(picker._visible_rows):
            if r.agent_name == "deepagent":
                table.move_cursor(row=idx)
                break
        await pilot.pause()
        cursor_session = picker._visible_rows[table.cursor_row].session_id
        assert cursor_session == "sess-3"

        # Open the filter and narrow to "deep" — only sess-3 survives.
        inp = picker.query_one("#filter-input", Input)
        picker.action_filter()
        await pilot.pause()
        inp.value = "deep"
        await pilot.pause()
        assert table.row_count == 1
        # Cursor lands on the surviving session (row 0 because only
        # one row is visible).
        assert picker._visible_rows[table.cursor_row].session_id == "sess-3"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_cursor_clamps_when_session_gone_from_filter(
    sample_rows: list[SessionRow],
) -> None:
    """Cursor clamps to row 0 when the prior session is filtered out."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Move cursor to a row with agent_name=react.
        for idx, r in enumerate(picker._visible_rows):
            if r.agent_name == "react":
                table.move_cursor(row=idx)
                break
        await pilot.pause()
        # Apply a filter that excludes the react rows.
        inp = picker.query_one("#filter-input", Input)
        picker.action_filter()
        await pilot.pause()
        inp.value = "deep"
        await pilot.pause()
        # Only the deepagent row remains; cursor clamps to row 0.
        assert table.row_count == 1
        assert table.cursor_row == 0


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_focuses_table_when_first_session_appears(
    sample_rows: list[SessionRow],
) -> None:
    """Empty → populated recompose auto-focuses the new DataTable.

    Without ``call_after_refresh(_focus_table_if_present)`` in
    ``_do_rescan``, focus would stay on the empty-state Markdown
    hint after the table appears, and arrow keys / Enter would
    silently do nothing until the operator clicked into the table.
    """
    # Start with no rows so the empty branch composes.
    client = make_fake_client([])
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        # Sanity: the empty branch has no DataTable mounted.
        assert picker._table_or_none() is None

        # Swap the fake client so the next rescan returns sessions
        # — triggers the empty→populated recompose path.
        app._client = make_fake_client(sample_rows)
        await picker._do_rescan()
        # Pump for both the recompose AND the deferred focus call.
        await pilot.pause()
        await pilot.pause()

        table = picker._table_or_none()
        assert table is not None
        assert table.has_focus


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_picker_cursor_preserved_across_rescan_with_row_diff(
    sample_rows: list[SessionRow],
) -> None:
    """Rescan that drops other rows still points the cursor at our session."""
    client = make_fake_client(sample_rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, PickerScreen)
        table = picker.query_one(DataTable)
        # Move cursor to sess-2 (deepagent's sibling react row).
        for idx, r in enumerate(picker._visible_rows):
            if r.session_id == "sess-2":
                table.move_cursor(row=idx)
                break
        await pilot.pause()

        # Rescan returns only sess-2 + sess-3 (sess-1 ends). The
        # surviving sess-2 should re-anchor the cursor regardless of
        # its new index in the smaller list.
        app._client = make_fake_client([sample_rows[1], sample_rows[2]])
        await picker._do_rescan()
        await pilot.pause()
        assert picker._visible_rows[table.cursor_row].session_id == "sess-2"


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
