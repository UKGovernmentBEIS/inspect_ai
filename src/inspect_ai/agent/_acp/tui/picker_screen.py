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
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Markdown, Static
from textual.widgets._data_table import CellDoesNotExist

from .client import SessionRow
from .widgets._formatting import format_running, format_tokens

# Column keys — module constants so add_column, update_cell, and per-tick
# refreshes all reference the same string. A typo at one site silently
# breaks update_cell (CellDoesNotExist) without a column-set assertion.
_COL_SAMPLE = "sample"
_COL_TASK = "task"
_COL_EPOCH = "epoch"
_COL_AGENT = "agent"
_COL_TOKENS = "tokens"
_COL_RUNNING = "running"


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
        table = self._table_or_none()
        if table is None:
            return
        # Pressing Enter while typing in the filter Input means "apply
        # what's typed and return to the table" — defocus the input.
        inp = self._filter_input()
        if inp is not None and inp.has_focus:
            table.focus()
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
        table = self._table_or_none()
        if table is not None:
            table.focus()

    def _filter_input(self) -> Input | None:
        """The filter Input, or None when we're in the empty-state branch."""
        try:
            return self.query_one("#filter-input", Input)
        except NoMatches:
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
        # Track which row currently shows the "▸" gutter glyph so
        # cursor moves can clear the old one before setting the new.
        self._gutter_row_key: str | None = None

    def compose(self) -> ComposeResult:
        # Local import to break the import cycle — ``_widgets._header``
        # pulls ``format_tokens`` from this module for the tokens chip
        # on the session header. Keeping the import inside compose
        # defers it until after this module is fully initialized.
        from .widgets import AppHeaderWidget

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
        table.add_column(_COL_SAMPLE, key=_COL_SAMPLE)
        table.add_columns(_COL_TASK, _COL_EPOCH, _COL_AGENT)
        # Use literal string keys (NOT ``str(ColumnKey)`` — that
        # returns the object's repr, which doesn't match anything on
        # lookup). update_cell calls in _tick_column reference the
        # same constants.
        table.add_column(_COL_TOKENS, key=_COL_TOKENS)
        table.add_column(_COL_RUNNING, key=_COL_RUNNING)
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
            table = self._table_or_none()
            if table is None:
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
                format_tokens(row.total_tokens),
                format_running(row.started_at, now),
                key=row.session_id,
            )
        self._gutter_row_key = (
            self._visible_rows[0].session_id if self._visible_rows else None
        )

    def _refresh_status(self) -> None:
        try:
            status = self.query_one("#picker-status", Static)
        except NoMatches:
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
        table = self._table_or_none()
        if table is None:
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
                        _COL_SAMPLE,
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
                _COL_SAMPLE,
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
        table = self._table_or_none()
        if table is not None:
            table.focus()
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
        """Background rescan: pull fresh rows, recompose only on structural change.

        Three outcomes per cycle:
        - same session-id set → in-place ``tokens`` refresh (cursor /
          scroll preserved).
        - structural change (empty ↔ populated branch transition, or
          population set diff while no table is mounted) → recompose.
        - row diff with table mounted → in-place repopulate via the
          filter path so the active filter stays applied.
        """
        if self._rescan is None:
            return
        try:
            new_rows = await self._rescan()
        except Exception:
            # Transient enumeration failures shouldn't disturb the
            # current view; try again next tick.
            return
        if not self._row_ids_changed(new_rows):
            # Steady state for the *set* of sessions, but per-row
            # fields (notably ``total_tokens``) may have advanced.
            self._rows = new_rows
            self._visible_rows = [
                r for r in self._rows if _row_matches(r, self._filter_text)
            ]
            self._tick_tokens()
            return
        self._rows = new_rows
        if self._needs_recompose(new_rows):
            self._visible_rows = [
                r for r in self._rows if _row_matches(r, self._filter_text)
            ]
            self.refresh(recompose=True)
            return
        # Row diff with a live table — reapply the filter in place so
        # rescanning during filtering doesn't drop back to unfiltered.
        self._apply_filter()

    def _row_ids_changed(self, new_rows: list[SessionRow]) -> bool:
        return [r.session_id for r in new_rows] != [r.session_id for r in self._rows]

    def _needs_recompose(self, new_rows: list[SessionRow]) -> bool:
        """True when we must swap structural branches (empty ↔ populated).

        Going to / from the empty branch flips which widgets exist; a
        partial mutation can't recover. Also covers the case where
        the empty branch is mounted (no DataTable yet) but new rows
        just arrived — we need a recompose to bring the table into
        being.
        """
        if not new_rows:
            return True
        return self._table_or_none() is None

    def _tick_running(self) -> None:
        """Per-second refresh of the ``running`` column — drives the live timer."""
        now = time.time()
        self._tick_column(
            _COL_RUNNING, lambda row: format_running(row.started_at, now)
        )

    def _tick_tokens(self) -> None:
        """Refresh the ``tokens`` column after a rescan pulls fresh data.

        Token totals only advance when the rescan loop pulls new data
        from the server — there's no local computation to redo every
        second — so this is wired into ``_do_rescan`` rather than the
        per-second tick.
        """
        self._tick_column(_COL_TOKENS, lambda row: format_tokens(row.total_tokens))

    def _tick_column(self, col_key: str, value_fn: Callable[[SessionRow], str]) -> None:
        """Update one column's cells in place across the visible rows.

        Silently skips when the table isn't mounted (table not yet
        composed, or we're sitting in the empty-state branch); the
        next tick will pick it up. ``CellDoesNotExist`` per row is
        also silenced — a concurrent rescan may have dropped the row
        between visible-rows snapshot and cell update.
        """
        if not self._visible_rows:
            return
        table = self._table_or_none()
        if table is None:
            return
        for row in self._visible_rows:
            try:
                table.update_cell(row.session_id, col_key, value_fn(row))
            except CellDoesNotExist:
                continue

    def _table_or_none(self) -> DataTable[str | Text] | None:
        """The mounted DataTable, or None if we're in the empty branch."""
        try:
            return self.query_one(DataTable)
        except NoMatches:
            return None

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
