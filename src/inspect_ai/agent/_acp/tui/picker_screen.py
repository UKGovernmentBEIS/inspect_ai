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
from textual.widgets import DataTable, Input, Markdown, Static
from textual.widgets._data_table import CellDoesNotExist

from .client import SessionRow
from .widgets import AppFooter
from .widgets._formatting import format_running, format_tokens

# Column keys — module constants so add_column, update_cell, and per-tick
# refreshes all reference the same string. A typo at one site silently
# breaks update_cell (CellDoesNotExist) without a column-set assertion.
# Keys stay stable (``"agent"``) even though the visible header is
# ``"acp agent"`` — letting the header drift from the key would mean
# every update_cell site needs auditing.
_COL_SAMPLE = "sample"
_COL_TASK = "task"
_COL_EPOCH = "epoch"
_COL_AGENT = "agent"
_COL_AGENT_HEADER = "acp agent"
_COL_TOKENS = "tokens"
_COL_RUNNING = "running"

# Intervention docs URL. Surfaced in the empty-state, in the status row
# when no ACP-compatible agents are present, and in the toast that
# fires when the operator tries to attach to a non-ACP row.
_INTERVENTION_URL = "https://inspect.aisi.org.uk/intervention.html"


def _display_task(task: str) -> str:
    """Drop the namespace prefix for display.

    Picker rows are typically scoped within one eval suite, so the
    leading ``namespace/`` (e.g. ``inspect_evals/``) is redundant
    noise. Splits on the FIRST slash so multi-segment task names like
    ``inspect_evals/swe_bench`` show as ``swe_bench``. With no slash
    we return the original string; with an empty tail (trailing
    slash) we fall back to the head so a malformed ``"namespace/"``
    still renders as ``"namespace"`` rather than an empty cell.
    """
    head, sep, tail = task.partition("/")
    if not sep:
        return task
    return tail or head


def _sort_rows(rows: list[SessionRow]) -> list[SessionRow]:
    """Order: ACP-attachable first; within each group, longest running first.

    Primary key: ``session_id is None`` (False sorts first, so ACP rows
    precede non-ACP rows). Within each group: ``None`` ``started_at``
    (no claim yet) sorts after every timestamped row; ties break on
    ``(eval_id, sample_id, epoch)`` so the order is fully
    deterministic and stable across rescans — new samples join at the
    bottom of their group, finished samples drop out, existing samples
    don't reorder.
    """
    return sorted(
        rows,
        key=lambda r: (
            r.session_id is None,
            r.started_at is None,
            r.started_at if r.started_at is not None else 0.0,
            r.eval_id,
            r.sample_id,
            r.epoch,
        ),
    )


def _is_acp(row: SessionRow) -> bool:
    """True when the row's sample has an attachable ACP session."""
    return row.session_id is not None


def _row_key(row: SessionRow) -> str:
    """Stable DataTable row key.

    ACP rows use their live ``session_id``. Non-ACP rows synthesize a
    key from ``(eval_id, task, sample_id, epoch)`` so every row in
    the table still has a unique, string-typed key (DataTable doesn't
    accept ``None`` as a key, and we need consistent keys across
    rescans so the cursor restoration in ``_populate_table`` can land
    back on the prior row).

    ``task`` is part of the synthesized key because multi-task eval
    suites routinely run different tasks with the same ``sample_id`` /
    ``epoch`` — collapsing them under one key would collide in
    ``DataTable.add_row`` and lose the second row silently.
    """
    if row.session_id is not None:
        return row.session_id
    return f"non-acp:{row.eval_id}:{row.task}:{row.sample_id}:{row.epoch}"


def _tokens_cell(n: int, *, dim: bool = False) -> Text:
    """Right-justified Rich Text for the tokens column.

    Centralised so add_row + update_cell (per-tick refresh) agree on
    the alignment shape — a Text wrapped on one side and a bare str
    on the other would lose the right-justify on the next tick.

    ``dim=True`` paints the cell with the muted style used for
    non-ACP rows.
    """
    style = "dim" if dim else ""
    return Text(format_tokens(n), justify="right", style=style)


def _running_cell(
    started_at: float | None, now: float | None = None, *, dim: bool = False
) -> Text:
    """Right-justified Rich Text for the running column.

    Mirrors :func:`_tokens_cell`'s alignment contract — both
    ``add_row`` and the per-tick ``update_cell`` go through this
    helper so the column stays right-aligned across ticks. Bare
    strings would lose the justify on the next refresh.
    """
    style = "dim" if dim else ""
    return Text(format_running(started_at, now), justify="right", style=style)


def _sample_cell(sample_id: str, *, is_cursor: bool, dim: bool = False) -> Text:
    """Sample-column cell value with an embedded cursor prefix.

    The leading ``▸ `` / ``  `` (always 2 chars) keeps every row's
    text aligned regardless of cursor state, AND avoids the
    double-space gap a dedicated 1-char gutter column would produce
    (DataTable's ``cell_padding: 1`` applies to BOTH adjacent columns,
    so an extra column adds 2 cells, not 1).
    """
    if is_cursor:
        # ``$warning`` (warm amber in the dark theme) matches the
        # plan-overlay running-row highlight, sharing one selection
        # vocabulary across the picker and the in-session plan view.
        cell = Text("▸ ", style="bold $warning")
        cell.append(sample_id, style="dim" if dim else "")
        return cell
    return Text(f"  {sample_id}", style="dim" if dim else "")


def _row_matches(row: SessionRow, query: str) -> bool:
    """Case-insensitive substring match across the user-visible fields.

    Task is matched against the *stripped* display form so the filter
    behaves consistently with what's on screen — typing
    ``inspect_evals`` against a row showing ``swe_bench`` (its
    stripped form) deliberately produces no match.
    """
    if not query:
        return True
    q = query.lower()
    return (
        q in (row.sample_id or "").lower()
        or q in _display_task(row.task or "").lower()
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
        self._activate(self._visible_rows[cursor_row])

    def _activate(self, row: SessionRow) -> None:
        """Gate attach attempts: non-ACP rows toast instead of attaching.

        ACP-claimed rows (``row.session_id is not None``) flow through
        to the app's ``on_select`` callback to open a session screen.
        Non-ACP rows have no live session_id to bind to — surface a
        brief warning toast so the operator knows the keystroke
        registered but won't attach. The intervention docs URL is
        intentionally NOT inlined in the toast: Textual notifications
        intercept clicks for dismissal, so an embedded link can't be
        opened anyway. The URL is always present in the status row
        (when no ACP rows are visible) and the empty-state copy —
        both Static surfaces where terminal OSC 8 click can reach it.
        """
        if row.session_id is None:
            self.app.notify(
                "No ACP-compatible agent for this sample.",
                severity="warning",
            )
            return
        self._on_select(row)

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
        border: tall $accent 30%;
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
       having to resort to ``!important``. ``$warning`` (warm amber
       in the dark theme) matches the plan-overlay running-row
       highlight, sharing one selection vocabulary across the
       picker and the in-session plan view. Focused state gets a
       stronger tint so the table reads as "active" without falling
       back to the saturated default. */
    PickerScreen DataTable > .datatable--cursor {
        background: $warning 28%;
        color: $text;
        text-style: none;
    }
    PickerScreen DataTable:focus > .datatable--cursor {
        background: $warning 42%;
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
        empty_notice: str | None = None,
    ) -> None:
        super().__init__()
        # Source-of-truth row list (everything enumeration returned),
        # sorted longest-running first. The sort is stable and applied
        # at every (re)assignment of ``_rows`` so derived views like
        # ``_visible_rows`` inherit the order automatically.
        self._rows = _sort_rows(rows)
        # Currently-displayed subset (after the filter substring is
        # applied). Mirrors ``_rows`` when ``_filter_text`` is empty.
        self._visible_rows: list[SessionRow] = list(self._rows)
        self._server_override = server_override
        self._on_select = on_select
        self._rescan = rescan
        # When the caller seeded a triple-filter (--task-id / --sample-id /
        # --epoch) that narrowed the list to zero, replace the default
        # empty-state body with a notice naming what didn't match so the
        # user understands why nothing's listed.
        self._empty_notice = empty_notice
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

        yield AppHeaderWidget(server=self._server_override)
        if not self._rows:
            yield from self._compose_empty()
        else:
            yield from self._compose_table()
        yield AppFooter()

    def _compose_empty(self) -> ComposeResult:
        # Triple-filter miss takes precedence over the other empty cases:
        # the user explicitly asked for one session and it isn't here, so
        # the standard "start an eval" or "connected to remote" copy would
        # be misleading.
        if self._empty_notice is not None:
            with Container(id="empty-state"):
                yield Static(self._empty_notice, classes="heading")
                yield Markdown(
                    "Re-run `inspect acp` without the filter arguments (or with a "
                    "different combination) to see the available sessions.",
                    classes="hint",
                )
            return
        # Differentiate the two empty cases: "no local discovery" vs
        # "explicit --server reachable but no sessions". The hint
        # command only applies to the former.
        if self._server_override is None:
            heading = "No running Inspect evals found on this machine."
            hint_md = (
                "Run eval or eval-set with the ACP server enabled, "
                "then return here:\n\n"
                "```bash\n"
                "# start server\n"
                "inspect eval <task> --acp-server\n"
                "```\n\n"
                "To use ACP with a remote machine, pass a host/port "
                "to `--acp-server`:\n\n"
                "```bash\n"
                "# start server\n"
                'inspect eval <task> --acp-server "0.0.0.0:4545"\n\n'
                "# connect to server\n"
                # 198.51.100.0/24 is the RFC 5737 reserved
                # documentation block; "98.51.100.0" was a typo
                # missing the leading "1" and is a real allocated
                # address.
                'inspect acp --server "198.51.100.0:4545"\n'
                "```\n"
                f"\nLearn how to enable ACP in your agent: <{_INTERVENTION_URL}>\n"
            )
        else:
            heading = (
                f"Connected to {self._server_override}, but no sessions "
                "have claimed ACP yet."
            )
            hint_md = (
                "Sessions appear once an agent's first turn begins.\n\n"
                f"Learn how to enable ACP in your agent: <{_INTERVENTION_URL}>\n"
            )
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

        # Zebra stripes alternate row backgrounds so it's easier to
        # track values across the row at a glance — useful once the
        # picker grows past a handful of rows. `sample` leads (most
        # identifying field); `eval` is intentionally NOT a column —
        # the eval id lives in the SessionScreen meta row once
        # attached. The count summary above already tells the user
        # how many evals are in play.
        table: DataTable[str | Text] = DataTable(cursor_type="row", zebra_stripes=True)
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
        # Order: ``epoch`` sits adjacent to ``sample`` so the two
        # identifying numbers read together; ``task`` follows since
        # it's the dim narrative column the eye skims past.
        table.add_columns(_COL_EPOCH, _COL_TASK)
        # Use literal string keys (NOT ``str(ColumnKey)`` — that
        # returns the object's repr, which doesn't match anything on
        # lookup). update_cell calls in _tick_column reference the
        # same constants.
        # Visible header reads ``acp agent`` so operators glance at
        # the column and immediately understand that the ``—`` cells
        # below are non-ACP samples (no attachable agent). Key stays
        # ``"agent"`` so update_cell sites need no audit.
        table.add_column(_COL_AGENT_HEADER, key=_COL_AGENT)
        # Tokens + running headers are right-justified to match their
        # cell values (cells get the same Text wrap via the
        # ``_tokens_cell`` / ``_running_cell`` helpers).
        table.add_column(Text(_COL_TOKENS, justify="right"), key=_COL_TOKENS)
        table.add_column(Text(_COL_RUNNING, justify="right"), key=_COL_RUNNING)
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
        # When the visible rows include zero ACP-attachable samples,
        # tack on a hint pointing at the intervention docs — operators
        # who see only dimmed rows otherwise have nothing to act on.
        # Triggers in both the all-non-ACP case AND when a filter
        # narrows the visible set to non-ACP rows only; mixed views
        # leave the existing summary intact since the row dimming
        # already telegraphs the split.
        if n_samples > 0 and not any(_is_acp(r) for r in self._visible_rows):
            # ``[link="URL"]…[/link]`` becomes an OSC 8 hyperlink in
            # supporting terminals. The URL MUST be quoted — Textual's
            # markup parser (which renders Static content too) treats
            # ``://`` in a bare value as malformed and raises
            # ``MarkupError``; quoting tells the parser "everything
            # inside the quotes is the value".
            return (
                "No ACP-compatible agents — see "
                f'[link="{_INTERVENTION_URL}"]{_INTERVENTION_URL}[/link]'
                f"   [dim]{count_chunk}[/dim]"
            )
        return f"Choose a running sample to connect to   [dim]{count_chunk}[/dim]"

    def _populate_table(self, table: DataTable[str | Text] | None = None) -> None:
        """(Re)build the table body from ``_visible_rows`` in place.

        Called at compose time (initial paint) and from
        ``_apply_filter`` so the displayed row set follows the filter
        without recomposing the whole screen (recompose would steal
        focus from the filter Input and break live typing).

        Cursor preservation: ``table.clear()`` resets the DataTable
        cursor to row 0, which is annoying when the user has scrolled
        to a specific row or is typing into the filter. Capture the
        highlighted session_id beforehand and restore the cursor to
        that session's new position (or clamp to row 0 when the
        session is no longer visible).
        """
        if table is None:
            table = self._table_or_none()
            if table is None:
                return
        # Snapshot the highlighted row key (if any) so we can land
        # the cursor back on the same row after the rebuild.
        prior_cursor_key: str | None = None
        if table.row_count > 0 and 0 <= table.cursor_row < len(self._visible_rows):
            prior_cursor_key = _row_key(self._visible_rows[table.cursor_row])
        # ``clear()`` drops rows but keeps the column layout, which is
        # what we want when narrowing/widening the visible set.
        table.clear()
        now = time.time()
        for idx, row in enumerate(self._visible_rows):
            is_acp = _is_acp(row)
            # ▸ glyph embedded as a 2-char prefix in the sample cell
            # (▸ + space + sample_id, or 2 leading spaces for
            # non-cursor rows). on_data_table_row_highlighted swaps
            # the prefix as the cursor moves. Non-ACP rows pass
            # ``dim=True`` to every cell helper so the whole row
            # reads as muted at a glance.
            agent_cell: Text = (
                Text("—", style="dim") if not is_acp else Text(row.agent_name or "—")
            )
            task_text = _display_task(row.task)
            task_cell = Text(task_text, style="dim")
            epoch_cell = Text(str(row.epoch), style="dim" if not is_acp else "")
            table.add_row(
                _sample_cell(row.sample_id, is_cursor=(idx == 0), dim=not is_acp),
                epoch_cell,
                # Task column is already dim for every row (the mockup
                # keeps it muted so the eye lands on sample id /
                # agent / time). Non-ACP rows get the same dim style;
                # no extra branch needed here.
                task_cell,
                agent_cell,
                _tokens_cell(row.total_tokens, dim=not is_acp),
                _running_cell(row.started_at, now, dim=not is_acp),
                key=_row_key(row),
            )
        # Restore cursor: prefer the previously-highlighted row key
        # if it's still visible, else clamp to row 0. The ▸ glyph is
        # on row 0 (from add_row's ``is_cursor=(idx == 0)``) so seed
        # ``_gutter_row_key`` to row 0's key and let
        # ``on_data_table_row_highlighted`` swap the glyph when the
        # cursor move fires the highlight event.
        if not self._visible_rows:
            self._gutter_row_key = None
            return
        new_index = 0
        if prior_cursor_key is not None:
            for idx, row in enumerate(self._visible_rows):
                if _row_key(row) == prior_cursor_key:
                    new_index = idx
                    break
        self._gutter_row_key = _row_key(self._visible_rows[0])
        if new_index != 0:
            table.move_cursor(row=new_index, animate=False)

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
        rows_by_key = {_row_key(r): r for r in self._visible_rows}
        if self._gutter_row_key is not None:
            prev = rows_by_key.get(self._gutter_row_key)
            if prev is not None:
                try:
                    table.update_cell(
                        self._gutter_row_key,
                        _COL_SAMPLE,
                        _sample_cell(
                            prev.sample_id, is_cursor=False, dim=not _is_acp(prev)
                        ),
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
                _sample_cell(
                    new_row.sample_id, is_cursor=True, dim=not _is_acp(new_row)
                ),
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
        self._focus_table_if_present()
        if self._table_or_none() is not None:
            # Per-second refresh of the running column so elapsed times
            # tick visibly. Cheap (in-place cell update).
            self.set_interval(1.0, self._tick_running)
        # Background rescan so new evals appear and finished ones
        # drop without a manual key press. Only recomposes when the
        # session-id set actually changes (compare before redraw) so
        # cursor / scroll state survive in steady state.
        if self._rescan is not None:
            self.set_interval(self.RESCAN_INTERVAL_SECS, self._do_rescan)

    def _focus_table_if_present(self) -> None:
        """Focus the DataTable if it's mounted; no-op in the empty branch.

        Used at initial mount AND after the empty→populated recompose
        so the operator can navigate / press Enter immediately when
        the first session appears, without first having to click into
        the table to take focus away from the (hidden) filter Input.
        """
        table = self._table_or_none()
        if table is not None:
            table.focus()

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
        # Sort up front so both the steady-state and the diff branches
        # observe the canonical order.
        new_rows = _sort_rows(new_rows)
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
            # Recompose is queued; the new DataTable isn't mounted
            # yet, so defer the focus to after the next layout pass.
            # Without this, the empty→populated transition leaves
            # focus on whatever the empty-state branch had (the
            # Markdown hint) and arrow keys / Enter would do nothing
            # until the operator clicked or tabbed into the table.
            self.call_after_refresh(self._focus_table_if_present)
            return
        # Row diff with a live table — reapply the filter in place so
        # rescanning during filtering doesn't drop back to unfiltered.
        self._apply_filter()

    def _row_ids_changed(self, new_rows: list[SessionRow]) -> bool:
        return [_row_key(r) for r in new_rows] != [_row_key(r) for r in self._rows]

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
        """Per-second refresh of the ``running`` column — drives the live timer.

        Wraps via ``_running_cell`` so the right-justify alignment
        survives every cell update (a bare string would drop back
        to the column's default left alignment on each tick).
        """
        now = time.time()
        self._tick_column(
            _COL_RUNNING,
            lambda row: _running_cell(row.started_at, now, dim=not _is_acp(row)),
        )

    def _tick_tokens(self) -> None:
        """Refresh the ``tokens`` column after a rescan pulls fresh data.

        Token totals only advance when the rescan loop pulls new data
        from the server — there's no local computation to redo every
        second — so this is wired into ``_do_rescan`` rather than the
        per-second tick. Wraps via ``_tokens_cell`` so the
        right-justify alignment survives every cell update.
        """
        self._tick_column(
            _COL_TOKENS,
            lambda row: _tokens_cell(row.total_tokens, dim=not _is_acp(row)),
        )

    def _tick_column(
        self,
        col_key: str,
        value_fn: Callable[[SessionRow], str | Text],
    ) -> None:
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
                table.update_cell(_row_key(row), col_key, value_fn(row))
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
        row_key = event.row_key.value
        for row in self._visible_rows:
            if _row_key(row) == row_key:
                self._activate(row)
                return
                return
