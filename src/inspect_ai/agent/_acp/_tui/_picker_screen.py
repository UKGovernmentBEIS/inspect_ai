"""Picker screen for the ``inspect acp`` TUI.

Two branches by row count:

- Empty: bootstrap message with the command to enable an ACP server
  on a local eval. Shown both at startup (no discovered evals) and on
  manual rescan when the discovery dir becomes empty.
- Populated: ``DataTable`` of running sessions; row activation
  callbacks into the App to open a ``SessionScreen``.

Bare-letter key bindings are intentionally *not* added here — the
design doc reserves them for modals & pickers, but since the App
hosts a composer in Phase 3 we keep the picker keymap minimal.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Markdown, Static
from textual.widgets._data_table import CellDoesNotExist

from ._client import SessionRow


def _format_running(started_at: float | None, now: float | None = None) -> str:
    """Format elapsed seconds as e.g. ``12s`` / ``3m 04s`` / ``1h 02m``."""
    if started_at is None:
        return "—"
    elapsed = (now if now is not None else time.time()) - started_at
    if elapsed < 0:
        elapsed = 0
    total = int(elapsed)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m, s = divmod(total, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}m"


def _format_tokens(n: int) -> str:
    """Pretty-format token counts with K / M / B suffixes.

    Token totals routinely cross the million mark on long agent runs;
    a literal ``1234567`` is hard to scan in a narrow column. Use the
    same convention model dashboards do: drop to one decimal place
    once the number rolls over to the next unit, then trim the
    trailing ``.0`` for clean values (``1.5K``, ``1K``, ``10.2M``).
    """
    if n < 1_000:
        return str(n)
    for unit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= unit:
            value = n / unit
            # One decimal for under-10 values (``1.2K``, ``9.9M``);
            # whole numbers above that so the column stays narrow.
            if value < 10:
                text = f"{value:.1f}"
            else:
                text = f"{value:.0f}"
            # Trim a useless trailing ``.0`` so ``1000`` reads as
            # ``1K`` rather than ``1.0K``.
            if text.endswith(".0"):
                text = text[:-2]
            return f"{text}{suffix}"
    return str(n)  # unreachable, keeps mypy happy


def _sample_cell(sample_id: str, *, is_cursor: bool) -> Text:
    """Sample-column cell value with an embedded cursor prefix.

    The leading ``▸ `` / ``  `` (always 2 chars) keeps every row's
    text aligned regardless of cursor state, AND avoids the
    double-space gap a dedicated 1-char gutter column would produce
    (DataTable's ``cell_padding: 1`` applies to BOTH adjacent columns,
    so an extra column adds 2 cells, not 1).
    """
    if is_cursor:
        cell = Text("▸ ", style="bold $primary")
        cell.append(sample_id)
        return cell
    return Text(f"  {sample_id}")


def _row_matches(row: SessionRow, query: str) -> bool:
    """Case-insensitive substring match across the user-visible fields."""
    if not query:
        return True
    q = query.lower()
    return (
        q in (row.sample_id or "").lower()
        or q in (row.task or "").lower()
        or q in (row.agent_name or "").lower()
    )


class PickerScreen(Screen[None]):
    """Always the initial screen; lists running ACP sessions."""

    # ``enter`` is bound with ``priority=True`` so it wins over the
    # focused DataTable's own (hidden) enter binding — without
    # priority, the focused widget binds first and the Screen-level
    # ``↵ attach`` hint never surfaces in the Footer. Same idea for
    # ``slash``: priority ensures the footer hint stays visible even
    # when DataTable is focused. ``slash`` is *also* the character the
    # user types into the filter Input — ``action_filter`` handles
    # that case by inserting the character at the cursor (the binding
    # would otherwise consume the keypress and the user could never
    # type ``/`` into the filter).
    BINDINGS = [
        Binding("enter", "attach", "attach", show=True, key_display="↵", priority=True),
        Binding(
            "up,down",
            "noop",
            "navigate",
            show=True,
            key_display="↑↓",
        ),
        Binding("slash", "filter", "filter", show=True, key_display="/", priority=True),
        Binding("escape", "cancel_filter", show=False),
    ]

    def action_noop(self) -> None:
        # Cosmetic-only handler — the bound keys are caught by the
        # DataTable first; this is here so Textual doesn't complain
        # about a missing action.
        pass

    def action_attach(self) -> None:
        """Activate the highlighted row (or commit the filter)."""
        # Pressing Enter while typing in the filter Input means "apply
        # what's typed and return to the table" — defocus the input.
        inp = self._filter_input()
        if inp is not None and inp.has_focus:
            try:
                table = self.query_one(DataTable)
            except Exception:
                return
            table.focus()
            return
        try:
            table = self.query_one(DataTable)
        except Exception:
            return
        if not self._visible_rows:
            return
        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._visible_rows):
            return
        self._on_select(self._visible_rows[cursor_row])

    def action_filter(self) -> None:
        """Open the filter Input — or, if it's already focused, insert ``/``."""
        inp = self._filter_input()
        if inp is None:
            # Empty branch — there's nothing to filter; tell the user
            # rather than silently dropping the keypress.
            self.app.notify(
                "Nothing to filter — no sessions to choose from.",
                severity="information",
            )
            return
        if inp.has_focus:
            # The Screen-level ``slash`` binding has priority over the
            # focused widget, so the Input never sees the keystroke.
            # Inject the character at the cursor so users can actually
            # type ``/`` into the filter.
            cur = inp.cursor_position
            inp.value = inp.value[:cur] + "/" + inp.value[cur:]
            inp.cursor_position = cur + 1
            return
        inp.remove_class("hidden")
        inp.focus()

    def action_cancel_filter(self) -> None:
        """Esc clears + hides the filter Input and refocuses the table."""
        inp = self._filter_input()
        if inp is None or inp.has_class("hidden"):
            return
        inp.value = ""
        inp.add_class("hidden")
        self._filter_text = ""
        self._apply_filter()
        try:
            self.query_one(DataTable).focus()
        except Exception:
            pass

    def _filter_input(self) -> Input | None:
        try:
            return self.query_one("#filter-input", Input)
        except Exception:
            return None

    DEFAULT_CSS = """
    PickerScreen { layout: vertical; }
    #empty-state { padding: 2 4; }
    #empty-state .heading { text-style: bold; padding-bottom: 2; }
    #empty-state .hint {
        color: $text-muted;
        /* Markdown widget defaults to `padding: 0 2 0 2` which would
           indent body text relative to the heading. Zero the left
           padding so paragraphs sit flush; fenced code blocks keep
           their own visual indent from Markdown's fence styling. */
        padding: 0;
        margin: 0;
    }
    /* Indent the status row to align with the table content (which
       picks up its own left padding from the DataTable below). */
    #picker-status {
        padding: 1 2;
        height: auto;
        color: $text-muted;
    }
    #picker-status .count { color: $foreground; text-style: bold; }
    /* Filter input lives just under the status row; muted background
       so it reads like a search affordance rather than a primary
       control. Hidden by default — `/` reveals it; Esc clears + hides. */
    #filter-input {
        margin: 0 2;
        height: 3;
        border: tall $primary 30%;
    }
    #filter-input.hidden { display: none; }
    /* Table inset uses ``margin`` (not ``padding``) so the table's
       own ``$surface`` background — plus the ``background-tint`` it
       adds on focus — stays inside the widget. With padding, the
       tinted area extended into the gutter and created a subtle
       coloured rectangle around the table that didn't quite match
       the screen background. */
    DataTable {
        height: 1fr;
        margin: 0 2;
    }
    /* Subtle cursor highlight — Textual's defaults paint the cursor
       with ``$block-cursor-background`` (a near-saturated accent)
       which reads more like a "Selected" button than a transcript
       ribbon. The selectors below scope to ``PickerScreen DataTable``
       so they outrank Textual's widget-default selectors (which have
       lower specificity once we add the screen prefix), without
       having to resort to ``!important``. Focused state gets a
       slightly stronger tint so the table reads as "active" without
       falling back to the saturated default. */
    PickerScreen DataTable > .datatable--cursor {
        background: $primary 20%;
        color: $text;
        text-style: none;
    }
    PickerScreen DataTable:focus > .datatable--cursor {
        background: $primary 35%;
        color: $text;
        text-style: none;
    }
    PickerScreen DataTable > .datatable--header { color: $text-muted; }
    """

    RESCAN_INTERVAL_SECS = 3.0
    """How often the picker re-enumerates sessions in the background.

    Each rescan opens a fresh connection to every discovered eval +
    calls ``initialize`` + ``inspect/list_sessions`` + closes — cheap
    enough to do every few seconds on local sockets, and the token
    column needs reasonably-fresh data to feel "live" during a run.
    """

    def __init__(
        self,
        *,
        rows: list[SessionRow],
        server_override: str | None,
        on_select: Callable[[SessionRow], None],
        rescan: Callable[[], Awaitable[list[SessionRow]]] | None = None,
    ) -> None:
        super().__init__()
        # Source-of-truth row list (everything enumeration returned).
        self._rows = rows
        # Currently-displayed subset (after the filter substring is
        # applied). Mirrors ``_rows`` when ``_filter_text`` is empty.
        self._visible_rows: list[SessionRow] = list(rows)
        self._server_override = server_override
        self._on_select = on_select
        self._rescan = rescan
        # Current filter query — kept as state on the screen so a
        # rescan that arrives while filtering can reapply it instead
        # of dropping back to the unfiltered view.
        self._filter_text = ""
        # Key for the "running" column; captured in _compose_table so
        # the per-second refresh can update those cells in place.
        self._running_col_key: str | None = None
        # Track which row currently shows the "▸" gutter glyph so
        # cursor moves can clear the old one before setting the new.
        self._gutter_row_key: str | None = None

    def compose(self) -> ComposeResult:
        # Local import to break the import cycle — ``_widgets._header``
        # pulls ``_format_tokens`` from this module for the tokens chip
        # on the session header. Keeping the import inside compose
        # defers it until after this module is fully initialized.
        from ._widgets import AppHeaderWidget

        yield AppHeaderWidget()
        if not self._rows:
            yield from self._compose_empty()
        else:
            yield from self._compose_table()
        yield Footer()

    def _compose_empty(self) -> ComposeResult:
        # Differentiate the two empty cases: "no local discovery" vs
        # "explicit --server reachable but no sessions". The hint
        # command only applies to the former.
        if self._server_override is None:
            heading = "No running Inspect evals found on this machine."
            hint_md = (
                "Run eval or eval-set with the ACP server enabled, "
                "then return here:\n\n"
                "```bash\n"
                "inspect eval <task> --acp-server\n"
                "```\n\n"
                "To use ACP with a remote machine, pass a host/port "
                "to `--acp-server`:\n\n"
                "```bash\n"
                'inspect eval <task> --acp-server "0.0.0.0:4545"\n'
                "```\n"
            )
        else:
            heading = (
                f"Connected to {self._server_override}, but no sessions "
                "have claimed ACP yet."
            )
            hint_md = "Sessions appear once an agent's first turn begins."
        with Container(id="empty-state"):
            yield Static(heading, classes="heading")
            yield Markdown(hint_md, classes="hint")

    def _compose_table(self) -> ComposeResult:
        yield Static(self._status_markup(), id="picker-status", markup=True)
        # Filter input — hidden by default; ``/`` reveals it. Adding
        # it to the tree at compose-time (rather than mounting on
        # demand) keeps the layout stable and avoids re-mount churn.
        yield Input(
            placeholder="filter samples...", id="filter-input", classes="hidden"
        )

        # No zebra stripes — clean dark background with a single
        # highlighted cursor row. `sample` leads (it's the most
        # identifying field); `eval` is intentionally NOT a column —
        # the eval id lives in the SessionScreen meta row once
        # attached. The count summary above already tells the user
        # how many evals are in play.
        table: DataTable[str | Text] = DataTable(cursor_type="row", zebra_stripes=False)
        # The ▸ cursor glyph is embedded into the sample cell itself
        # (rather than living in its own gutter column) so we get a
        # single space between glyph and sample text. A separate
        # column would double the gap to two spaces — DataTable's
        # uniform ``cell_padding: 1`` adds the right-pad of the gutter
        # AND the left-pad of the sample column, with no per-column
        # override available.
        # Explicit ``key="sample"`` so on_data_table_row_highlighted
        # can ``update_cell(row_key, "sample", …)`` — add_columns
        # would assign auto-generated UUID keys, breaking the swap.
        table.add_column("sample", key="sample")
        table.add_columns("task", "epoch", "agent")
        # Use literal string keys (NOT ``str(ColumnKey)`` — that
        # returns the object's repr, which doesn't match anything on
        # lookup). The same strings passed here are what update_cell
        # references in _tick_running.
        table.add_column("tokens", key="tokens")
        table.add_column("running", key="running")
        self._running_col_key = "running"
        self._populate_table(table)
        with Vertical():
            yield table

    def _status_markup(self) -> str:
        n_samples = len(self._visible_rows)
        n_total = len(self._rows)
        n_evals = len({row.eval_id for row in self._visible_rows})
        eval_word = "eval" if n_evals == 1 else "evals"
        sample_word = "sample" if n_samples == 1 else "samples"
        # When a filter is active and narrows the set, surface the
        # ``N of M`` shape so the user knows there are more rows
        # behind the filter.
        if self._filter_text and n_samples != n_total:
            count_chunk = (
                f"{n_samples} of {n_total} {sample_word} · {n_evals} {eval_word}"
            )
        else:
            count_chunk = f"{n_samples} {sample_word} · {n_evals} {eval_word}"
        return f"Choose a running sample to connect to   [dim]{count_chunk}[/dim]"

    def _populate_table(self, table: DataTable[str | Text] | None = None) -> None:
        """(Re)build the table body from ``_visible_rows`` in place.

        Called at compose time (initial paint) and from
        ``_apply_filter`` so the displayed row set follows the filter
        without recomposing the whole screen (recompose would steal
        focus from the filter Input and break live typing).
        """
        if table is None:
            try:
                table = self.query_one(DataTable)
            except Exception:
                return
        # ``clear()`` drops rows but keeps the column layout, which is
        # what we want when narrowing/widening the visible set.
        table.clear()
        now = time.time()
        for idx, row in enumerate(self._visible_rows):
            # ▸ glyph embedded as a 2-char prefix in the sample cell
            # (▸ + space + sample_id, or 2 leading spaces for
            # non-cursor rows). on_data_table_row_highlighted swaps
            # the prefix as the cursor moves.
            table.add_row(
                _sample_cell(row.sample_id, is_cursor=(idx == 0)),
                # Dim the task column — the mockup keeps it muted so
                # the eye lands on sample id / agent / time.
                Text(row.task, style="dim"),
                str(row.epoch),
                row.agent_name or "—",
                _format_tokens(row.total_tokens),
                _format_running(row.started_at, now),
                key=row.session_id,
            )
        self._gutter_row_key = (
            self._visible_rows[0].session_id if self._visible_rows else None
        )

    def _refresh_status(self) -> None:
        try:
            status = self.query_one("#picker-status", Static)
        except Exception:
            return
        status.update(self._status_markup())

    def _apply_filter(self) -> None:
        """Recompute ``_visible_rows`` from ``_filter_text`` and redraw."""
        self._visible_rows = [
            r for r in self._rows if _row_matches(r, self._filter_text)
        ]
        self._populate_table()
        self._refresh_status()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter as the user types in the filter Input."""
        if event.input.id != "filter-input":
            return
        self._filter_text = event.value
        self._apply_filter()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Move the ▸ glyph to follow the cursor as it navigates."""
        try:
            table = self.query_one(DataTable)
        except Exception:
            return
        new_key = event.row_key.value if event.row_key is not None else None
        if new_key is None or new_key == self._gutter_row_key:
            return
        # Look up sample_id for each affected row so we can rebuild
        # the cell value with the cursor prefix swapped.
        rows_by_key = {r.session_id: r for r in self._visible_rows}
        if self._gutter_row_key is not None:
            prev = rows_by_key.get(self._gutter_row_key)
            if prev is not None:
                try:
                    table.update_cell(
                        self._gutter_row_key,
                        "sample",
                        _sample_cell(prev.sample_id, is_cursor=False),
                    )
                except CellDoesNotExist:
                    pass
        new_row = rows_by_key.get(new_key)
        if new_row is None:
            return
        try:
            table.update_cell(
                new_key,
                "sample",
                _sample_cell(new_row.sample_id, is_cursor=True),
            )
        except CellDoesNotExist:
            return
        self._gutter_row_key = new_key

    def on_mount(self) -> None:
        # Textual auto-focuses the first focusable widget in DOM
        # order, which is the (hidden) filter Input. That would route
        # Enter/arrow keys to the Input instead of the table; force
        # focus to the table so navigation + attach work out of the
        # gate. Only meaningful in the populated branch — the empty
        # branch has no DataTable.
        if self._rows:
            try:
                self.query_one(DataTable).focus()
            except Exception:
                pass
            # Per-second refresh of the running column so elapsed times
            # tick visibly. Cheap (in-place cell update).
            self.set_interval(1.0, self._tick_running)
        # Background rescan so new evals appear and finished ones
        # drop without a manual key press. Only recomposes when the
        # session-id set actually changes (compare before redraw) so
        # cursor / scroll state survive in steady state.
        if self._rescan is not None:
            self.set_interval(self.RESCAN_INTERVAL_SECS, self._do_rescan)

    async def _do_rescan(self) -> None:
        if self._rescan is None:
            return
        try:
            new_rows = await self._rescan()
        except Exception:
            # Transient enumeration failures shouldn't disturb the
            # current view; try again next tick.
            return
        new_ids = [r.session_id for r in new_rows]
        cur_ids = [r.session_id for r in self._rows]
        if new_ids == cur_ids:
            # Steady state for the *set* of sessions, but per-row
            # fields (notably ``total_tokens``) may have advanced
            # since the last rescan. Replace ``_rows`` so subsequent
            # ticks see fresh data, then update the ``tokens`` cells
            # in place so the user sees the new values without losing
            # cursor / scroll state.
            self._rows = new_rows
            self._visible_rows = [
                r for r in self._rows if _row_matches(r, self._filter_text)
            ]
            self._tick_tokens()
            return
        self._rows = new_rows
        if not new_rows:
            # Need to swap to the empty branch — that's a structural
            # change, not just a row-set diff. Recompose handles it.
            self._visible_rows = []
            self.refresh(recompose=True)
            return
        # Reapply the active filter (if any) so a rescan during
        # filtering doesn't drop back to the unfiltered view. If we
        # were previously in the empty branch (no table mounted), a
        # recompose is still required to bring the table into being.
        try:
            self.query_one(DataTable)
        except Exception:
            self._visible_rows = [
                r for r in self._rows if _row_matches(r, self._filter_text)
            ]
            self.refresh(recompose=True)
            return
        self._apply_filter()

    def _tick_running(self) -> None:
        if not self._visible_rows or self._running_col_key is None:
            return
        try:
            table = self.query_one(DataTable)
        except Exception:
            # Table not mounted (e.g. tick fired between empty-state
            # branches); next tick will pick it up.
            return
        now = time.time()
        for row in self._visible_rows:
            try:
                table.update_cell(
                    row.session_id,
                    self._running_col_key,
                    _format_running(row.started_at, now),
                )
            except CellDoesNotExist:
                # Row was removed (e.g. concurrent rescan) — fine,
                # skip. Narrow except so we don't mask real bugs
                # like a stale column-key string (previous regression).
                continue

    def _tick_tokens(self) -> None:
        """Update the ``tokens`` column from the current ``_visible_rows``.

        Separate from ``_tick_running`` because token totals only
        advance when the rescan pulls fresh data from the server —
        there's no local computation to redo every second. Called from
        ``_do_rescan`` after refreshing ``_rows``.
        """
        if not self._visible_rows:
            return
        try:
            table = self.query_one(DataTable)
        except Exception:
            return
        for row in self._visible_rows:
            try:
                table.update_cell(
                    row.session_id,
                    "tokens",
                    _format_tokens(row.total_tokens),
                )
            except CellDoesNotExist:
                continue

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Belt-and-braces: ``action_attach`` (Screen-level ``enter``
        # binding) is the primary path now that we use ``priority=True``.
        # This handler still fires for explicit row selection events
        # (e.g. tests dispatching RowSelected directly) and for
        # alternate activation paths that DataTable might emit.
        session_id = event.row_key.value
        for row in self._visible_rows:
            if row.session_id == session_id:
                self._on_select(row)
                return
