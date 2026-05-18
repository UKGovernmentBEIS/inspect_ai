"""Plan strip + expanded-overlay widgets.

Surfaces the agent's current plan (collapsed `update_plan` /
`todo_write` invocations, delivered by the server's
:class:`PlanPolicyTransformer` as ``AgentPlanUpdate`` notifications
once the TUI opts in via ``inspect.plan_rendering``).

Two widgets:

- :class:`PlanStripWidget` — one-line strip pinned above the composer,
  showing ``plan [✓ done/total] current: <task>… ^``. Auto-hides when
  the agent hasn't emitted a plan yet. Clicking the strip OR pressing
  ``^p`` opens the overlay.
- :class:`PlanOverlayScreen` — ``ModalScreen`` rendered as a
  full-width slab that covers the strip and extends upward into the
  transcript area. No scrim (transcript above stays visible).
  Height-capped so it never grows past the app header; internally
  scrollable for long plans; opens scrolled to the bottom so the
  most-recent entries are visible. ``esc`` / ``^p`` / clicking the
  ``x`` dismisses.

The strip subscribes to :class:`SessionState` directly. The overlay
takes a frozen snapshot at open time — plans rarely change mid-glance,
and freezing avoids fighting the scroll position the user is reading.
"""

from __future__ import annotations

from typing import Callable

from acp.schema import PlanEntry
from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Click
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from ..state import SessionState

# Glyphs picked so each status has a distinct *shape* before colour
# registers. Mirrors the design spec's plan-row vocabulary. Leading
# ``\`` escapes the ``[`` for Rich markup — without it Rich treats
# ``[◐]`` as an unknown style tag and raises ``MarkupError``.
_STATUS_GLYPH: dict[str, str] = {
    "pending": "\\[ ]",
    "in_progress": "\\[◐]",
    "completed": "\\[✓]",
}

_STRIP_CHEVRON = "▴"
"""Trailing affordance on the collapsed strip — signals "expandable upward".

``▴`` (U+25B4 BLACK UP-POINTING SMALL TRIANGLE) — conventional UI
affordance for "click to expand", paired naturally with the
inverse ``▾`` collapse glyph used elsewhere. Quieter than the
full-size ``▲`` so it doesn't compete with the strip's content.
"""

_PLAN_LABEL_COLOR = "#d4a168"
"""Hex tint for the ``plan`` label on the strip + overlay header.

Soft warm amber — close to Textual's default-theme ``$warning``
without going loud. Used directly in Rich markup (``[#d4a168]``)
since Rich doesn't expand Textual's ``$`` theme tokens at markup
time; the value lives here as a single constant so the strip and
overlay header stay in lock-step.
"""

_OVERLAY_DISMISS = "x"
"""Trailing affordance on the overlay header — click to dismiss."""

# Bottom-margin lift on the expanded card. Leaves a clear breathing
# row between the popup's bottom edge and the composer's top border
# — eliminating it caused the popup to visually overlay the
# composer chrome. Composition: composer-row (3) + footer (1) +
# 2-row breathing gap above the composer = 6 bottom rows reserved.
_OVERLAY_BOTTOM_LIFT = 6


class PlanStripWidget(Widget):
    """One-row plan summary, click- or ``^p``-expandable.

    Hidden via ``display = False`` whenever the session has no plan
    (the agent never invoked ``update_plan`` / ``todo_write``). The
    spec's "no clutter for non-planning agents" requirement.
    """

    DEFAULT_CSS = """
    PlanStripWidget {
        height: 1;
        margin: 0 2;
        padding: 0 1;
        /* Same tint as the overlay's body + titlebar — visually
         * unifies the collapsed strip with the expanded popup. A
         * ``$foreground X%`` blend (rather than the opaque
         * code-block slate) keeps the plan chrome distinct when the
         * popup overlays a code block; an identical opaque colour
         * would make their boundaries disappear into each other. */
        background: $foreground 20%;
    }
    PlanStripWidget.-hidden { display: none; }
    PlanStripWidget Horizontal { height: 1; }
    /* Left "plan [✓ 2/5] current: …" stretches; trailing chevron is
     * fixed-width and right-docked so the truncation absorbs the
     * length variation. */
    PlanStripWidget #plan-strip-body { width: 1fr; }
    PlanStripWidget #plan-strip-chevron {
        width: 2;
        color: $foreground 40%;
        content-align: right middle;
    }
    """

    def __init__(self, state: SessionState) -> None:
        super().__init__()
        self._state = state
        self._unsubscribe: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("", id="plan-strip-body", markup=True)
            yield Static(_STRIP_CHEVRON, id="plan-strip-chevron", markup=False)

    def on_mount(self) -> None:
        self._unsubscribe = self._state.subscribe(self._refresh_from_state)
        self._refresh_from_state()

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    async def on_click(self, event: Click) -> None:
        # Mouse parity with the screen's ``ctrl+p`` binding. Use
        # ``run_action`` (not ``self.app.action_*``) so the screen's
        # handler — which knows whether the overlay is currently up —
        # owns the toggle decision. Stop the event so the click
        # doesn't also propagate to the transcript focus.
        event.stop()
        await self.screen.run_action("toggle_plan")

    def _refresh_from_state(self) -> None:
        """Re-render from current ``SessionState``; toggles visibility."""
        entries = self._state.plan_entries
        if entries is None:
            # No plan yet — hide entirely. The next AgentPlanUpdate
            # will flip the class off and the strip will appear.
            self.add_class("-hidden")
            return
        self.remove_class("-hidden")
        try:
            body = self.query_one("#plan-strip-body", Static)
        except NoMatches:
            return  # not mounted yet; on_mount will retry
        done = self._state.plan_done_count
        total = self._state.plan_total_count
        current = self._state.plan_current_entry
        body.update(self._format_body(done, total, current))

    @staticmethod
    def _format_body(done: int, total: int, current: PlanEntry | None) -> str:
        # Three-tier hierarchy across the strip:
        #
        # - ``plan`` (the section label) gets a subtle warm amber so
        #   the operator's eye anchors there first — same family as
        #   the in-progress chrome elsewhere in the TUI without going
        #   loud. Rich markup doesn't expand Textual's ``$warning``
        #   token, so we use a hex close to the default-theme amber.
        # - ``current:`` (the right-side sub-label) stays dim — it's
        #   chrome, not content.
        # - The task content itself is ALSO dim so the whole right
        #   side reads as one lighter band rather than as a label
        #   (dim) attached to a brighter value (default fg). This
        #   keeps the strip quiet between glances.
        #
        # The ``[✓ done/total]`` tally uses the same check glyph the
        # row marker does for completed rows — visually couples the
        # tally to the entries it summarizes.
        if total == 0:
            # Forward-compat path: the agent emitted an explicitly
            # empty plan (cleared its todos). Render a neutral
            # placeholder rather than going blank.
            return (
                f"[{_PLAN_LABEL_COLOR}]plan[/{_PLAN_LABEL_COLOR}] "
                "\\[[green]✓[/green] 0/0]   [dim]no entries[/dim]"
            )
        if current is None:
            # All entries completed — show the count and a finished
            # marker. Done count == total in this branch.
            return (
                f"[{_PLAN_LABEL_COLOR}]plan[/{_PLAN_LABEL_COLOR}] "
                f"\\[[green]✓[/green] {done}/{total}]   [dim]all complete[/dim]"
            )
        # No row-status glyph next to ``current:`` — the right side
        # is just the task content. The status icon lives in the
        # expanded overlay; on the collapsed strip it's redundant
        # chrome that competes with the task title for attention.
        return (
            f"[{_PLAN_LABEL_COLOR}]plan[/{_PLAN_LABEL_COLOR}] "
            f"\\[[green]✓[/green] {done}/{total}]   "
            f"[dim]current: {_escape_markup(current.content)}[/dim]"
        )


class PlanOverlayScreen(ModalScreen[None]):
    """Expanded-plan card anchored above the strip.

    Pushed by ``SessionScreen.action_toggle_plan`` and popped on
    ``esc``, ``^p``, or clicking the ``x`` glyph. Subscribes to the
    same :class:`SessionState` the strip reads so plan updates that
    land while the overlay is open are reflected in place (statuses
    flip, new entries appear, completed entries grey out — without
    closing + re-opening).

    Height-capped at 80% viewport so the card never fills the whole
    screen. Long plans scroll inside the card. On open the rows are
    auto-scrolled past any already-completed entries so the first
    non-completed row lands at the top of the viewport — operators
    skip the history they've already seen. If the agent's "current"
    row advances while the overlay is open, the scroll re-aligns so
    the new current row stays visible.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "close", show=False),
        # ``priority`` so ``^p`` here wins over the SessionScreen
        # binding (which would otherwise re-toggle, opening a second
        # overlay on top of the dismissed one).
        Binding("ctrl+p", "dismiss", "close", show=False, priority=True),
    ]

    DEFAULT_CSS = f"""
    PlanOverlayScreen {{
        /* Bottom-aligned + horizontal centre so the card sits flush
         * above the composer area. Background is fully transparent
         * — the transcript above the card stays at full brightness
         * (no scrim/dim) so the operator can keep reading it while
         * glancing at the plan. */
        align: center bottom;
        background: transparent;
    }}
    PlanOverlayScreen #plan-overlay-card {{
        /* Structural container only — no background. The header
         * and rows children each set their own background so they
         * blend over the same base (the transparent screen → dark
         * terminal bg) as the collapsed strip. Layering a card
         * background under them would brighten the children
         * unpredictably and the header would NOT match the strip's
         * colour even with identical CSS values. */
        width: 100%;
        height: auto;
        max-height: 80%;
        background: transparent;
        border: none;
        /* Symmetric 2-column gutters on each side — matches the
         * composer-row's outer margins so the card's vertical edges
         * line up with the composer below. Bottom-margin keeps the
         * card one row above the composer's top border (see
         * ``_OVERLAY_BOTTOM_LIFT`` comment). */
        margin: 0 2 {_OVERLAY_BOTTOM_LIFT} 2;
        padding: 0;
    }}
    PlanOverlayScreen #plan-overlay-header {{
        /* Same tint as the rows body and the collapsed strip — the
         * whole plan surface (strip → titlebar → rows) reads as one
         * uniform elevated band. The titlebar is structurally
         * distinct (different widget, different content) but the
         * background is intentionally identical so the popup feels
         * like the strip simply opened upward. */
        height: 1;
        padding: 0 1;
        background: $foreground 20%;
    }}
    PlanOverlayScreen #plan-overlay-header-label {{ width: 1fr; }}
    PlanOverlayScreen #plan-overlay-dismiss {{
        width: 2;
        color: $foreground 50%;
        content-align: right middle;
    }}
    PlanOverlayScreen #plan-overlay-dismiss:hover {{
        color: $text;
    }}
    PlanOverlayScreen #plan-overlay-rows {{
        height: auto;
        max-height: 100%;
        /* Card body tint lives HERE (rather than on the card) so
         * the header above blends over the same base (transparent
         * screen) as the collapsed strip — see the card's CSS
         * comment for the layering rationale. The rows region still
         * needs an opaque-ish background so the transcript behind
         * the modal doesn't bleed through behind the task list. */
        background: $foreground 20%;
        /* No vertical padding: the titlebar band above (its own
         * background) is the visual separator from the rows below,
         * and the card ends flush with the last row. Horizontal
         * padding at 1 col insets from the card's edges. */
        padding: 0 1;
    }}
    PlanOverlayScreen .plan-row {{ height: auto; }}
    PlanOverlayScreen .plan-row.-running {{
        background: $warning 15%;
        color: $warning;
    }}
    PlanOverlayScreen .plan-row.-completed {{
        color: $foreground 50%;
    }}
    """

    def __init__(self, state: SessionState) -> None:
        super().__init__()
        self._state = state
        self._unsubscribe: Callable[[], None] | None = None
        # Index of the first non-completed entry at the last refresh.
        # Used to decide whether a state change should re-align scroll
        # (focus moved → re-scroll) vs leave the operator's current
        # scroll position alone (statuses changed but the focused row
        # didn't move).
        self._last_focus_index: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="plan-overlay-card"):
            with Horizontal(id="plan-overlay-header"):
                yield Static("", id="plan-overlay-header-label", markup=True)
                yield Static(_OVERLAY_DISMISS, id="plan-overlay-dismiss", markup=False)
            yield VerticalScroll(id="plan-overlay-rows")

    def on_mount(self) -> None:
        # Initial render + auto-scroll past completed entries.
        # Subscribe AFTER the initial render so the first paint goes
        # through the same refresh path as later state-change-driven
        # updates. ``call_after_refresh`` defers the scroll until the
        # rows we just mounted have actually been laid out (their
        # ``region``/``virtual_size`` populated) — running the scroll
        # synchronously in ``on_mount`` no-ops because
        # ``scroll_to_widget`` reads layout data that hasn't been
        # computed yet.
        self._refresh_from_state()
        self.call_after_refresh(self._auto_scroll)
        self._unsubscribe = self._state.subscribe(self._on_state_change)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _on_state_change(self) -> None:
        """Sync rows to current state; re-scroll only if focus moved."""
        prev_focus = self._last_focus_index
        self._refresh_from_state()
        if self._last_focus_index != prev_focus:
            # Deferred for the same layout-timing reason as the
            # initial mount: when ``_refresh_from_state`` takes the
            # rebuild path (entry count changed), the new rows aren't
            # laid out yet, so ``scroll_to_widget`` would no-op.
            self.call_after_refresh(self._auto_scroll)

    def _refresh_from_state(self) -> None:
        """Repaint header + rows from the current ``SessionState``.

        Updates row text + status classes in place when the entry
        count is stable (the common case — ``update_plan`` typically
        toggles statuses on a fixed-length list). Falls back to a
        full rebuild when the length changes, since adding/removing
        rows requires (un)mounting widgets anyway.
        """
        try:
            header = self.query_one("#plan-overlay-header-label", Static)
            scroll = self.query_one("#plan-overlay-rows", VerticalScroll)
        except NoMatches:
            return  # compose hasn't completed yet
        entries = self._state.plan_entries or []
        done = self._state.plan_done_count
        total = self._state.plan_total_count
        header.update(self._header_markup(done, total))
        existing = [c for c in scroll.children if isinstance(c, Static)]
        if len(existing) == len(entries):
            # Same shape — update each row in place. Preserves
            # operator scroll position across pure status flips.
            for widget, entry in zip(existing, entries):
                widget.update(self._row_markup(entry))
                _set_row_classes(widget, entry)
        else:
            # Length changed — rebuild rows. Rare for plan tools,
            # but happens when the agent restructures its plan
            # mid-session.
            scroll.remove_children()
            for entry in entries:
                scroll.mount(
                    Static(
                        self._row_markup(entry),
                        classes=self._row_classes(entry),
                        markup=True,
                    )
                )
        self._last_focus_index = self._state.plan_current_index

    def _auto_scroll(self) -> None:
        """Scroll so the row the strip considers "current" sits at the top.

        Reads :attr:`SessionState.plan_current_index` — the same
        source of truth the collapsed strip uses for its "current:
        …" line. Keeping both surfaces on one selection rule
        prevents the strip from saying "current: B" while the
        overlay opens on row A (which can happen with a
        ``[pending A, in_progress B]`` ordering if each surface
        runs its own first-non-completed scan).

        Three paths:
        - No plan: nothing to scroll.
        - All entries completed (``current_index is None``): scroll
          to the bottom — the most recent completion is the
          meaningful "what happened" anchor.
        - Otherwise: scroll so the current row sits at the top of
          the viewport.
        """
        try:
            scroll = self.query_one("#plan-overlay-rows", VerticalScroll)
        except NoMatches:
            return
        entries = self._state.plan_entries or []
        if not entries:
            return
        focus = self._state.plan_current_index
        if focus is None:
            scroll.scroll_end(animate=False)
            return
        children = [c for c in scroll.children if isinstance(c, Static)]
        if 0 <= focus < len(children):
            scroll.scroll_to_widget(children[focus], top=True, animate=False)

    def on_click(self, event: Click) -> None:
        # Any click anywhere — on the ``x``, inside the card, or on
        # the transparent area above — dismisses. The overlay has no
        # in-card interactivity in v1 (rows are read-only), so a
        # click is unambiguously "I'm done looking at this." Symmetric
        # with the strip's click-to-open behaviour: click to expand,
        # click again to collapse.
        event.stop()
        self.dismiss()

    async def action_dismiss(self, result: None = None) -> None:
        # Wrapper so the binding's action name matches Textual's
        # ``ModalScreen.dismiss`` method signature without us having
        # to spell ``dismiss(None)`` in the binding string. Async to
        # match Screen.action_dismiss' return type contract.
        self.dismiss()

    @staticmethod
    def _header_markup(done: int, total: int) -> str:
        # Mirrors the strip's "plan [✓ done/total]" left side so the
        # operator's eye lands on the same anchor whether the widget
        # is collapsed or expanded. The per-row status (in_progress /
        # pending / completed) is already conveyed by the row glyphs
        # below; adding a duplicate "in progress" / "ready" suffix
        # here is redundant chrome.
        return (
            f"[{_PLAN_LABEL_COLOR}]plan[/{_PLAN_LABEL_COLOR}] "
            f"\\[[green]✓[/green] {done}/{total}]"
        )

    @staticmethod
    def _row_markup(entry: PlanEntry) -> str:
        glyph = _STATUS_GLYPH.get(entry.status, "[ ]")
        content = _escape_markup(entry.content)
        return f"{glyph} {content}"

    @staticmethod
    def _row_classes(entry: PlanEntry) -> str:
        # Two state classes for CSS targeting; pending is the default
        # (no class) so the row uses the standard foreground colour.
        if entry.status == "in_progress":
            return "plan-row -running"
        if entry.status == "completed":
            return "plan-row -completed"
        return "plan-row"


def _set_row_classes(widget: Static, entry: PlanEntry) -> None:
    """Reconcile a row's status classes for an in-place update.

    Strips any prior ``-running`` / ``-completed`` state class then
    applies the one matching the entry's current status. ``plan-row``
    stays on always — it's the structural class our CSS keys off.
    """
    for cls in ("-running", "-completed"):
        widget.remove_class(cls)
    widget.add_class("plan-row")
    if entry.status == "in_progress":
        widget.add_class("-running")
    elif entry.status == "completed":
        widget.add_class("-completed")


def _escape_markup(text: str) -> str:
    r"""Escape Rich-markup metacharacters so user content can't break rendering.

    Plan-entry content is operator-supplied via the agent and may
    contain ``[`` (e.g. ``"[draft] write tests"``), ``]``, or literal
    backslashes that, in front of a ``[``, would smuggle styling
    into our markup. Delegates to ``rich.markup.escape`` — the
    canonical Rich helper that doubles backslashes BEFORE escaping
    the brackets, so a payload like ``r"\\[/dim]bad"`` survives
    without raising ``MarkupError`` or leaking styles.
    """
    return rich_escape(text)
