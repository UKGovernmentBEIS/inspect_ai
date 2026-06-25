"""Tool-call card widget — renders one :class:`ToolCallState`.

Composition (matches :class:`MessageWidget`'s bullet + indented-body
layout so tool calls read as another row in the conversation, not a
visually distinct card):

- Header: coloured bullet + tool name + dim args.
- Body: indented under the tool name (``padding-left: 2``). Per
  content variant — text content blocks, native
  :class:`FileEditToolCallContent` diff, terminal placeholder.
No footer row. The status glyph (✓/✗/spinner) lives in the header's
bullet position and the elapsed timer rides as a dim ``· Ns`` suffix
on the same line, so the whole tool-call outcome groups in one anchor.
Status is carried by the glyph alone — no border colour — to match
the calmer, flush layout the message widget uses.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai._util.rich import clean_control_characters

from ..state import ApprovalDecisionLabel, ToolCallState
from ._collapsible import CollapsibleContent
from ._fingerprint import item_signature
from ._formatting import SPINNER_FRAMES, format_duration

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_OUTPUT_MAX_LINES = 15
"""How many lines of tool output to show before truncating.

Long bash outputs / file dumps blow out the transcript otherwise. The
trailing ``[+N more lines]`` indicator tells the operator something
was elided.
"""

# Completed tool calls get a gear (``⚙``) rather than the generic
# ``✓``. The gear reads as "this row is a tool" semantically — the
# message bullets are circular (``•``), the score chip uses ``★``,
# the event chips use kind-specific glyphs (``⚠`` / ``↺`` / ``ⓘ``);
# the gear keeps tool calls visually distinct from those families.
# ``✗`` on failure still pops red so error rows are easy to scan.
_COMPLETED_GLYPH = "⚙"
_FAILED_GLYPH = "✗"

# Tool-call header glyphs render in the default text colour (no
# explicit wrap) so the row reads as plain conversation content
# rather than a coloured-accent chip. We previously used a Tokyo-
# Night cyan here, but that drew the eye to the glyph more than the
# tool name itself — and the tool name is what the operator actually
# wants to scan. The failed ✗ keeps a red wrap (via ``$error``) so
# errors still pop against the body text.
_FAILED_GLYPH_COLOR = "$error"


class ToolCallWidget(Widget):
    """Bullet-prefixed tool-call row, matched to :class:`MessageWidget`.

    No border: the colour-coded glyph (cyan) plus body indentation are
    the only structural cues. Status info lives in the leading glyph
    (✓ / ✗ / spinner) and the duration rides as a dim ``· Ns`` suffix
    on the same header row — no separate footer.
    """

    DEFAULT_CSS = """
    ToolCallWidget {
        height: auto;
        /* padding-bottom: 1 gives a row of trailing space below the
         * body so the next transcript item doesn't run flush against
         * the tool card's last content row. Internal padding (not
         * margin-bottom) so it never gets clipped by VerticalScroll
         * when the tool call is the last transcript item. */
        padding: 0 2 1 2;
    }
    /* padding-bottom: 1 gives the title row a blank line below it
     * before the first body item (code block / output / plan), so
     * the header reads as a heading instead of running into the
     * body content. When the card has no body content yet (in-flight,
     * pre-result, no pending approval), the ``.empty-body`` override
     * below zeros the padding so it doesn't stack with the widget's
     * own ``padding-bottom: 1`` and produce an extra blank row above
     * the next transcript item. */
    ToolCallWidget .header {
        height: auto;
        padding-bottom: 1;
    }
    ToolCallWidget.empty-body .header { padding-bottom: 0; }
    /* Body shares the tool-name indent so everything below the bullet
     * visually lines up under the *tool name* rather than the bullet
     * itself — parallel to MessageWidget's `.body` padding-left. */
    ToolCallWidget .body {
        height: auto;
        padding-left: 2;
    }
    /* Visual separation between successive content items (input view
     * vs output, multiple result blocks) — each item lives in its own
     * ``.content-item`` wrapper so update_state can append-only mount
     * new wrappers without disturbing existing ones, AND each gets a
     * bottom margin so the blocks read distinctly. Without this, the
     * input + output appeared as one continuous block with the
     * CollapsibleContent collapsed and blocks rendered flush. */
    ToolCallWidget .content-item {
        height: auto;
        margin-bottom: 1;
    }
    /* The last item's margin-bottom stacks with the widget's
     * ``padding: 0 2 1 2`` (padding-bottom: 1) to give 2 rows of
     * trailing space below the tool card — visible as an extra blank
     * row between the tool body and the next transcript item. Zero
     * the margin on the last item so the trailing space comes from
     * the widget padding alone (1 row, matching other transcript
     * items). Used to be absorbed by the footer row; that row is
     * gone now, exposing the double-source. */
    ToolCallWidget .content-item:last-child {
        margin-bottom: 0;
    }
    /* Truncation-note styling is on CollapsibleContent itself —
     * portable across tool cards + message bubbles. */
    ToolCallWidget .diff-header {
        color: $text-muted;
        text-style: italic;
    }
    ToolCallWidget .diff-old { color: $error; }
    ToolCallWidget .diff-new { color: $success; }
    ToolCallWidget .body-content { height: auto; }
    ToolCallWidget .plan-entry { height: auto; }
    ToolCallWidget .plan-spacer { height: 1; }
    /* Approval area sizes to its content (the inline approval section
     * while pending, empty otherwise — the post-resolution decision
     * text lives inline on the header row). Without an explicit
     * ``height: auto`` the Vertical inherits its ``1fr`` default and
     * eats the remaining vertical space in the card. */
    ToolCallWidget #approval-area { height: auto; }
    """

    def __init__(self, state: ToolCallState, *, defer_body: bool = False) -> None:
        super().__init__()
        self._state = state
        # When True, the body is held back even if ``state.content``
        # is populated. Set by :class:`TranscriptWidget` whenever ANY
        # OTHER tool is still actively running — covers both the
        # in-flight call-view (e.g. the bash command preview, a custom
        # viewer's input lookup) and the terminal result body. Under
        # parallel execution every card collapses to its single-line
        # header so the operator's eye stays on the in-flight set
        # rather than being pulled to one tool's body that jutted out
        # past its peers. Reveals all-at-once when the last sibling
        # settles.
        self._defer_body = defer_body
        # In-flight spinner frame, advanced by ``tick_duration``. Same
        # cadence as the assistant chip spinner (driven by the
        # SessionScreen's periodic timer).
        self._spinner_frame = 0
        # Snapshots of what's currently MOUNTED. update_state diffs
        # against these rather than the live state (which mutates in
        # place inside SessionState._merge_tool_fields) so we can
        # detect what actually changed and apply minimal DOM updates.
        self._mounted_header = self._header_text()
        self._mounted_status = self._state.status
        self._mounted_kind: str = "plan" if self._is_plan_state() else "content"
        # When the body is deferred, mounted_item_sigs reflects the
        # empty body that's actually mounted — NOT the items we're
        # holding back. The first un-defer pass then sees a delta
        # vs the (now visible) content and rebuilds wholesale. Without
        # this, the un-defer transition would see "no changes" and
        # leave the body empty.
        self._mounted_item_sigs: list[tuple[Any, ...]] = (
            [] if self._defer_body else self._compute_item_sigs()
        )
        # Tracks whether the approval section is currently mounted in
        # the approval-area. Diff against this in update_state to
        # mount/unmount minimally as ``pending_approval`` toggles.
        self._mounted_has_pending: bool = self._state.pending_approval is not None
        # Mirror of ``_defer_body`` at the last refresh — the empty-body
        # CSS class is derived from ``_has_visible_body()`` which folds
        # in defer state, so a defer→un-defer flip with no status change
        # would otherwise leave a stale ``empty-body`` class on the card.
        self._mounted_defer_body = self._defer_body
        self._refresh_status_class()

    # ------------------------------------------------------------------
    # Compose + initial render
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes="header", markup=True)
        # Approval area sits BETWEEN header and body: pending approvals
        # are visually the most important thing on the card when
        # present (the agent is blocked on us). Mounted dynamically by
        # ``_update_approval_area_if_changed`` — starts empty.
        with Vertical(id="approval-area"):
            yield from self._compose_approval_area()
        # Body is gated on ``_defer_body``: when the widget mounts in a
        # deferred state (e.g. another tool is still running while this
        # one starts up, or a reconnect / replay landing mid-parallel-
        # batch), the body Vertical mounts empty; the next
        # ``update_state`` with ``defer_body=False`` rebuilds it
        # wholesale.
        with Vertical(classes="body"):
            if not self._defer_body:
                yield from self._compose_body()

    def _refresh_status_class(self) -> None:
        for cls in ("in-flight", "completed", "failed"):
            self.remove_class(cls)
        if self._state.status == "failed":
            self.add_class("failed")
        elif self._state.status == "completed":
            self.add_class("completed")
        else:
            self.add_class("in-flight")
        # ``.approval`` is orthogonal to the status class — layered on
        # top so the approval section's visual hooks can apply without
        # affecting the existing in-flight / completed / failed
        # styling.
        if self._state.pending_approval is not None:
            self.add_class("approval")
        else:
            self.remove_class("approval")
        # ``.empty-body`` toggles the header's bottom padding — when
        # the card has no body content yet (in-flight, pre-result) and
        # no pending-approval section to mount, the padding stacks
        # with the widget's own ``padding-bottom: 1`` and shows as an
        # extra blank row between the tool header and whatever follows
        # in the transcript.
        if self._has_visible_body():
            self.remove_class("empty-body")
        else:
            self.add_class("empty-body")

    def _has_visible_body(self) -> bool:
        """Whether the card will actually render content below the header.

        True when there's body content (regular items, plan entries)
        OR a pending approval section. False on a freshly-mounted in-
        flight card that hasn't produced any output yet — that's the
        case where the header's ``padding-bottom: 1`` stacks with the
        widget's own bottom padding for a 2-row trailing gap.

        Returns False while ``_defer_body`` is set: even though the
        underlying state has content, we're not mounting it yet, so the
        card visually IS an empty-body card (same trailing-gap regime).
        """
        if self._state.pending_approval is not None:
            return True
        if self._defer_body:
            return False
        if self._state.content:
            return True
        if self._is_plan_state():
            return True
        return False

    # ------------------------------------------------------------------
    # Periodic tick — keeps in-flight spinner + elapsed advancing
    # ------------------------------------------------------------------

    def tick_duration(self) -> None:
        """Refresh the header so the in-flight spinner + elapsed advance.

        Called by the SessionScreen's periodic tick. Terminal states
        already show the final glyph + duration so we skip them and
        avoid needless DOM churn. Pending-approval states also skip:
        the header shows the static ``approval requested`` marker (no
        spinner, no duration) so the tick has nothing to advance.
        """
        if self._state.is_terminal or self._state.pending_approval is not None:
            return
        self._spinner_frame += 1
        try:
            new_header = self._header_text()
            self.query_one(".header", Static).update(new_header)
            self._mounted_header = new_header
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # State update — diff mounted vs. incoming and apply minimal patch
    # ------------------------------------------------------------------

    def update_state(self, state: ToolCallState, *, defer_body: bool = False) -> None:
        """Re-bind to (possibly mutated) state and apply minimal updates.

        Critical for live visual quality: a wholesale-rebuild on every
        notification flashed every tool card whenever any chunk
        arrived. This implementation diffs against the mounted
        snapshot and only touches what changed.

        Update strategy, applied top-to-bottom:

        - Header / status border — cheap re-render only when the
          header text changed.
        - Body items — gated on a fingerprint diff. When the body must
          change, pick exactly one of: wholesale rebuild, extend last
          item in place, or append-only mount. Fall back to wholesale
          rebuild when the diff doesn't fit those shapes.

        ``defer_body``: when True, suppress body mounting entirely —
        the body stays at whatever shape was last mounted (typically
        empty, since the gate is asserted by ``TranscriptWidget`` from
        the moment ANY other tool is running in parallel, covering
        both the call-view preview and the terminal result body).
        When the gate flips back to False (the last sibling settled),
        this method gets called again and the standard diff path
        mounts the held-back content.

        Defensive False→True transition: if a body was already mounted
        (e.g. the call-view was visible at start, then a sibling tool
        landed and formed a parallel batch), tear the mounted body
        down and reset the mounted sigs to ``[]``. The next un-defer
        pass then takes the simple append-only path. Without this
        clear, the stale body would stay visible while the gate said
        to hide it.
        """
        was_deferred = self._mounted_defer_body
        self._state = state
        self._defer_body = defer_body

        self._update_status_class_if_changed()
        self._update_header_if_changed()
        self._update_approval_area_if_changed()

        if self._defer_body:
            if not was_deferred:
                try:
                    body = self.query_one(".body", Vertical)
                    for child in list(body.children):
                        child.remove()
                except NoMatches:
                    pass
                self._mounted_item_sigs = []
            return

        if not self._body_changed():
            return

        try:
            body = self.query_one(".body", Vertical)
        except NoMatches:
            return

        new_sigs = self._compute_item_sigs()
        new_kind = "plan" if self._is_plan_state() else "content"

        if self._needs_wholesale_rebuild(new_kind, new_sigs):
            self._rebuild_body_wholesale(body)
        elif self._can_extend_last_item(new_sigs):
            items = self._state.content or []
            if not self._extend_last_content_item(body, items[-1]):
                self._rebuild_body_wholesale(body)
        elif self._can_append_only(new_sigs):
            self._append_new_items(body, new_sigs)
        else:
            self._rebuild_body_wholesale(body)

        self._mounted_item_sigs = new_sigs
        self._mounted_kind = new_kind

    # ------------------------------------------------------------------
    # Update-state helpers — small, named, side-effecting
    # ------------------------------------------------------------------

    def _update_status_class_if_changed(self) -> None:
        # Either path triggers a class refresh: status drives the
        # in-flight/completed/failed class, ``_defer_body`` drives
        # ``empty-body`` via ``_has_visible_body()``. Without the
        # defer-body branch, a parallel-sibling reveal (status stays
        # ``completed``, defer flips False) would mount the body but
        # leave the stale ``empty-body`` class on the card, pinning the
        # header's bottom padding to zero and visually clipping the
        # newly-revealed body against the header row.
        if (
            self._state.status != self._mounted_status
            or self._defer_body != self._mounted_defer_body
        ):
            self._refresh_status_class()
            self._mounted_status = self._state.status
            self._mounted_defer_body = self._defer_body

    def _update_header_if_changed(self) -> None:
        new_header = self._header_text()
        if new_header == self._mounted_header:
            return
        try:
            self.query_one(".header", Static).update(new_header)
        except NoMatches:
            pass
        self._mounted_header = new_header

    def _update_approval_area_if_changed(self) -> None:
        """Mount / unmount the approval section to match ``pending_approval``.

        Two transitions:
        - ``False → True``: a permission request just arrived. Mount
          the section.
        - ``True → False``: operator (or Esc / session completion)
          resolved. Unmount the section; the decision text appears
          inline on the header row (see ``_header_text``).
        Idle states (``False → False``, ``True → True``) are no-ops.

        Also refreshes the ``.approval`` CSS class on the card — it
        toggles with ``pending_approval`` (not with ``status``), so
        the regular ``_update_status_class_if_changed`` path can't
        catch this transition.
        """
        has_pending = self._state.pending_approval is not None
        if has_pending == self._mounted_has_pending:
            return
        try:
            area = self.query_one("#approval-area", Vertical)
        except NoMatches:
            return
        for child in list(area.children):
            child.remove()
        for w in self._compose_approval_area():
            area.mount(w)
        self._mounted_has_pending = has_pending
        # Approval CSS class transitions piggyback on this update — it
        # toggles with ``pending_approval`` independently of ``status``.
        self._refresh_status_class()

    def _compose_approval_area(self) -> ComposeResult:
        """Yield the approval section (or nothing).

        Post-resolution the decision lives on the header row, not
        here, so the area stays empty after the operator decides.
        """
        if self._state.pending_approval is not None:
            yield _ApprovalContent(self._state)

    def _body_changed(self) -> bool:
        new_kind = "plan" if self._is_plan_state() else "content"
        new_sigs = self._compute_item_sigs()
        return new_kind != self._mounted_kind or new_sigs != self._mounted_item_sigs

    # ------------------------------------------------------------------
    # Update-state predicates — pick at most one true at a time
    # ------------------------------------------------------------------

    def _needs_wholesale_rebuild(
        self, new_kind: str, new_sigs: list[tuple[Any, ...]]
    ) -> bool:
        """True when the body can't be patched in place.

        Triggers: kind switch (plan ↔ content), or any change inside
        a plan body (plans are short and rebuild cheaply). The
        empty-body case is handled by ``_can_append_only`` —
        ``[] → [item, …]`` has an empty common prefix equal to the
        empty mounted list, so the append-only path mounts the new
        items without a full teardown.
        """
        if new_kind != self._mounted_kind:
            return True
        return new_kind == "plan"

    def _can_extend_last_item(self, new_sigs: list[tuple[Any, ...]]) -> bool:
        """True when the only change is that the last content item grew.

        Streaming tool output (bash stdout, model thinking, etc.)
        produces this shape — same item count, all but the last item
        unchanged, last item is a longer text-content block. Avoids a
        full rebuild on every chunk.
        """
        old = self._mounted_item_sigs
        if len(new_sigs) != len(old) or not old:
            return False
        common = _common_prefix(old, new_sigs)
        if common != len(old) - 1:
            return False
        last_old, last_new = old[-1], new_sigs[-1]
        return bool(
            last_old[0] == "content"
            and last_new[0] == "content"
            and last_new[1] >= last_old[1]
        )

    def _can_append_only(self, new_sigs: list[tuple[Any, ...]]) -> bool:
        """True when existing items are unchanged and new items were appended."""
        old = self._mounted_item_sigs
        return _common_prefix(old, new_sigs) == len(old)

    # ------------------------------------------------------------------
    # Update-state mutators
    # ------------------------------------------------------------------

    def _append_new_items(
        self, body: Vertical, new_sigs: list[tuple[Any, ...]]
    ) -> None:
        common = len(self._mounted_item_sigs)
        items = self._state.content or []
        for item in items[common:]:
            wrapper = Vertical(classes="content-item")
            body.mount(wrapper)
            for w in self._compose_item(item):
                wrapper.mount(w)

    def _extend_last_content_item(self, body: Vertical, item: object) -> bool:
        """Replace the last content wrapper's body text with the new text.

        Returns False if the mounted DOM doesn't match the assumed
        single-CollapsibleContent shape (defensive — the body
        composition is the only path that creates these wrappers, but
        a future content variant might break the assumption). On False
        the caller falls back to wholesale rebuild.
        """
        children = list(body.children)
        if not children:
            return False
        last_wrapper = children[-1]
        if not isinstance(last_wrapper, Vertical):
            return False
        inner_children = list(last_wrapper.children)
        if len(inner_children) != 1:
            return False
        cc = inner_children[0]
        if not isinstance(cc, CollapsibleContent):
            return False
        text = self._text_for_inner(getattr(item, "content", None))
        if not text:
            return False
        cc.replace_text(clean_control_characters(text))
        return True

    def _rebuild_body_wholesale(self, body: Vertical) -> None:
        for child in list(body.children):
            child.remove()
        for w in self._compose_body():
            body.mount(w)

    # ------------------------------------------------------------------
    # Body composition
    # ------------------------------------------------------------------

    def _compose_body(self) -> ComposeResult:
        # Plan tools (update_plan, todo_write) carry the actual plan in
        # raw_input — the result content is usually just "Plan updated".
        # Render the entries as a checklist so the operator can see what
        # the agent committed to.
        plan_entries = self._extract_plan_entries()
        if plan_entries is not None:
            yield from self._compose_plan(plan_entries)
            return

        items = self._state.content or []
        # No items yet → empty body. The header (spinner glyph +
        # elapsed timer) already conveys "in flight, no output yet"
        # without a dedicated placeholder row.
        # Each content item lives in its own ``.content-item`` wrapper
        # so update_state can identify "the widget for item N" and
        # append-only mount new wrappers without disturbing existing
        # ones. Wrapping is what eliminates the flash you'd otherwise
        # get from tearing the whole body down on every progress.
        for item in items:
            with Vertical(classes="content-item"):
                yield from self._compose_item(item)

    def _compose_item(self, item: object) -> ComposeResult:
        """Render one body item; delegates to the module-level dispatcher.

        Kept as a thin instance wrapper so the widget's existing call
        sites don't churn; new call sites (e.g. ``_ApprovalContent``)
        should call :func:`compose_content_item` directly.
        """
        yield from compose_content_item(item, context_id=self._state.tool_call_id)

    def _compose_plan(self, entries: list[dict[str, Any]]) -> ComposeResult:
        for entry in entries:
            status = str(entry.get("status", "pending")).lower()
            text = _plan_entry_text(entry)
            if status == "completed":
                glyph = "[x]"
            elif status == "in_progress":
                glyph = "[~]"
            else:
                glyph = "[ ]"
            # Plain text — the glyph alone carries status. Per-state
            # colouring made finished plans read as a wall of green;
            # plain is calmer and more legible.
            yield Static(f"  {glyph} {text}", classes="plan-entry", markup=False)
        # Trailing blank row so the next transcript item doesn't press
        # against the last plan entry — CollapsibleContent does this
        # via its own margin-bottom, but the plan path bypasses that
        # widget.
        yield Static("", classes="plan-spacer", markup=False)

    # ------------------------------------------------------------------
    # Per-state derivations — header, footer, plan / fingerprint shape
    # ------------------------------------------------------------------

    def _header_text(self) -> str:
        """Header: status glyph + bold tool name + dim args · duration · …

        Mirrors :meth:`MessageWidget._chip_text` — coloured glyph on
        the left so the eye reads tool calls as another row in the
        conversation, with the body indented under the *tool name*.
        The glyph rotates between a braille spinner (in-flight), ✓
        (completed), and ✗ (failed); the elapsed timer rides as a
        dim ``· Ns`` suffix on the same line so the whole tool-call
        outcome (status, duration, approval decision, cancelling
        marker) groups in one anchor — no separate footer row.

        The router formats ``title`` via
        :func:`inspect_ai.agent._acp.tool_content.descriptive_title` —
        e.g. ``bash ls /usr/bin`` or ``update_plan``. Splitting on the
        first space recovers ``name`` vs argument summary so the eye
        lands on the *tool* first. We can't call ``descriptive_title``
        directly here: the TUI only receives the post-formatted string
        on the wire, not the raw ``(fn, arguments)`` pair the function
        needs.
        """
        # Status glyph in the bullet position: spinner while in
        # flight, ⚙ on success (renders in default text colour so the
        # row reads as plain conversation, not a coloured-accent
        # chip), ✗ on failure (red so errors pop). The colour split
        # mirrors how the assistant chip handles its own
        # spinner-vs-bullet transition: chrome stays quiet, only the
        # error state shouts.
        if self._state.status == "completed":
            glyph = _COMPLETED_GLYPH
            glyph_markup = glyph
        elif self._state.status == "failed":
            glyph = _FAILED_GLYPH
            glyph_markup = f"[{_FAILED_GLYPH_COLOR}]{glyph}[/]"
        else:
            glyph = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
            glyph_markup = glyph

        title = self._state.title or self._state.tool_call_id
        name, _, args = title.partition(" ")
        if args:
            args_escaped = args.replace("[", r"\[").replace("]", r"\]")
            base = f"{glyph_markup} [bold]{name}[/bold] [dim]{args_escaped}[/dim]"
        else:
            base = f"{glyph_markup} [bold]{name}[/bold]"

        # Pending approval: drop the timer (it'd be measuring operator
        # think-time, not tool work) and just signal the wait. The
        # spinner resumes ticking as soon as the operator decides.
        if self._state.pending_approval is not None:
            return f"{base} [dim]· approval requested[/]"

        # Duration in the header (dim, dot-separated). In-flight: derive
        # from start_time so the card surfaces progress without waiting
        # for a terminal status. Terminal: use the captured
        # ``duration_seconds`` so a finished card stops drifting.
        if self._state.is_terminal:
            duration = format_duration(self._state.duration_seconds)
        else:
            duration = format_duration(time.monotonic() - self._state.start_time)
        base = f"{base} [dim]· {duration}[/]"

        # Post-resolution approval decision rides as a coloured
        # ·-separated suffix — saves a separate row and keeps the whole
        # tool-call outcome in one scan line.
        decision = self._state.last_approval_decision
        if decision is not None:
            color = _DECISION_COLOR[decision]
            text = _DECISION_TEXT[decision]
            base = f"{base} [{color}]· {text}[/]"
        # Visual feedback for the screen-level ``^L cancel tool``
        # action: once the operator has fired the cancel, a dim
        # ``cancelling…`` marker appears until the synthesized failure
        # status lands. Suppressed during pending approval (the
        # approval bar owns "stop this tool"), but that path returned
        # early above.
        if not self._state.is_terminal and self._state.cancel_requested:
            base = f"{base} [dim]· cancelling…[/]"
        return base

    def _text_for_inner(self, inner: object) -> str:
        # TextContentBlock → text; everything else gets a placeholder
        # consistent with the message widget's handling.
        if inner is None:
            return ""
        if getattr(inner, "type", None) == "text":
            return getattr(inner, "text", "") or ""
        type_name = getattr(inner, "type", None) or "content"
        return f"[{type_name}]"

    def _compute_item_sigs(self) -> list[tuple[Any, ...]]:
        """Snapshot the current state's body items for later diffing.

        Plan-style tools render from ``raw_input`` not ``content``, so
        their snapshot is a single ``("plan", …)`` tuple — any change
        triggers a wholesale plan rebuild (plans are short and change
        less often than streamed output).
        """
        plan = self._extract_plan_entries()
        if plan is not None:
            return [("plan", tuple(_plan_entry_sig(e) for e in plan))]
        items = self._state.content or []
        return [item_signature(item) for item in items]

    def _is_plan_state(self) -> bool:
        return self._extract_plan_entries() is not None

    def _extract_plan_entries(self) -> list[dict[str, Any]] | None:
        """Return a checklist of plan items if this is a plan-style tool.

        Look at the title's first token (the tool name) to decide
        whether to interpret raw_input as a plan. ACP also has native
        ``AgentPlanUpdate`` notifications that arrive separately; this
        path covers the tool-call-as-plan flow Inspect's react agents
        use today.
        """
        title = (self._state.title or "").split(" ", 1)[0]
        if title not in ("update_plan", "todo_write", "todo"):
            return None
        raw = self._state.raw_input
        if not isinstance(raw, dict):
            return None
        for key in ("plan", "todos", "entries", "tasks"):
            entries = raw.get(key)
            if isinstance(entries, list) and all(isinstance(e, dict) for e in entries):
                return entries
        return None


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _plan_entry_text(entry: dict[str, Any]) -> str:
    """Display text for a plan entry — tries the keys Inspect tools emit.

    ``update_plan`` uses ``step``; ``todo_write`` uses ``content``;
    other plan-style tools may use ``text`` / ``description`` /
    ``task``. Falls through to the first non-empty value so the entry
    text always renders.
    """
    return str(
        entry.get("step")
        or entry.get("content")
        or entry.get("text")
        or entry.get("description")
        or entry.get("task")
        or ""
    )


def _plan_entry_sig(entry: dict[str, Any]) -> tuple[str, str]:
    status = str(entry.get("status", "pending")).lower()
    return (status, _plan_entry_text(entry))


def _common_prefix(old: list[tuple[Any, ...]], new: list[tuple[Any, ...]]) -> int:
    n = 0
    while n < len(old) and n < len(new) and old[n] == new[n]:
        n += 1
    return n


# ----------------------------------------------------------------------
# Content-item rendering — shared by the tool card body and the inline
# approval section. Module-level so ``_ApprovalContent`` can render the
# request's ``tool_call.content`` blocks (markdown / diff / terminal
# variants) through the same pipeline as a live tool card, honoring
# the tool author's custom presentation (via ``@tool(viewer=...)``).
# ----------------------------------------------------------------------


def compose_content_item(item: object, *, context_id: str = "") -> ComposeResult:
    """Dispatch one ACP ``ToolCallContent`` variant to its renderer.

    Three ACP variants per ``ToolCallUpdate.content``:
    - ``"content"`` (``ContentToolCallContent``) — wraps a markdown /
      text content block; rendered via :class:`CollapsibleContent`
      with truncation + syntax highlighting.
    - ``"diff"`` (``FileEditToolCallContent``) — bespoke
      ``--- path / - old / + new`` styling.
    - ``"terminal"`` (``TerminalToolCallContent``) — placeholder for
      the terminal id (full streaming-terminal rendering is deferred).

    ``context_id`` is logged on unknown content types for debugging.
    """
    type_name = getattr(item, "type", None)
    if type_name == "diff":
        yield from compose_diff_item(item)
        return
    if type_name == "terminal":
        terminal_id = getattr(item, "terminal_id", "?")
        yield Static(f"[terminal: {terminal_id}]", classes="body-content", markup=False)
        return
    if type_name == "content":
        inner = getattr(item, "content", None)
        text = _text_for_inner(inner)
        if not text:
            yield Static("", classes="body-content", markup=False)
            return
        # Clean control characters first — untrusted tool stdout can
        # include ANSI escapes / NUL bytes that confuse rich's
        # measurement pass.
        cleaned = clean_control_characters(text)
        yield CollapsibleContent(cleaned, max_lines=_DEFAULT_TOOL_OUTPUT_MAX_LINES)
        return
    logger.warning(
        "compose_content_item: unknown content item type %r (context_id=%s)",
        type_name,
        context_id,
    )
    yield Static(f"[{type_name or 'unknown'}]", classes="body-content", markup=False)


def compose_diff_item(item: object) -> ComposeResult:
    """Render a ``FileEditToolCallContent`` (ACP ``Diff`` variant)."""
    path = getattr(item, "path", "?")
    old_text = getattr(item, "old_text", None)
    new_text = getattr(item, "new_text", "") or ""
    yield Static(f"--- {path}", classes="diff-header", markup=False)
    if old_text:
        for line in old_text.splitlines() or [""]:
            yield Static(f"- {line}", classes="diff-old", markup=False)
    for line in new_text.splitlines() or [""]:
        yield Static(f"+ {line}", classes="diff-new", markup=False)


def _text_for_inner(inner: object) -> str:
    """Extract display text from a content block (text vs. placeholder)."""
    if inner is None:
        return ""
    if getattr(inner, "type", None) == "text":
        return getattr(inner, "text", "") or ""
    type_name = getattr(inner, "type", None) or "content"
    return f"[{type_name}]"


def _is_separator_block(block: object) -> bool:
    """True iff ``block`` is the producer-side ``---`` rule block.

    Used by :class:`_ApprovalContent` to apply a tight (no-margin)
    wrapper around the rule so it doesn't double-space the
    transition between view halves. Match shape: a
    ``ContentToolCallContent`` whose inner ``TextContentBlock.text``
    stripped equals ``---`` — exactly what
    ``_separator_block`` in ``approval/_human/acp.py`` emits.
    """
    if getattr(block, "type", None) != "content":
        return False
    inner = getattr(block, "content", None)
    if inner is None or getattr(inner, "type", None) != "text":
        return False
    return getattr(inner, "text", "").strip() == "---"


# ----------------------------------------------------------------------
# Approval section (inline on the tool-call card)
#
# The card hosts the CONTEXT PREVIEW (``_ApprovalContent`` below). The
# action buttons live on :class:`_ApprovalCard` (inline below the
# transcript) and post :class:`ApprovalDecisionRequested` using the
# ``_BUTTON_ID_PREFIX`` id convention defined here.
# ----------------------------------------------------------------------


class ApprovalDecisionRequested(Message):
    """Posted up from :class:`_ApprovalCard` when an action button is pressed.

    Routes to :meth:`SessionScreen.on_approval_decision_requested`
    which calls :meth:`SessionState.resolve_approval` — that fires the
    pending event the client-side JSON-RPC handler is parked on, and
    the response goes back over the wire.
    """

    def __init__(self, tool_call_id: str, option_id: str) -> None:
        super().__init__()
        self.tool_call_id = tool_call_id
        self.option_id = option_id


_BUTTON_ID_PREFIX = "approve-opt-"


class _ApprovalContent(Vertical):
    """Inline approval CONTEXT PREVIEW on a tool-call card.

    Renders the ``view.context`` / separator / ``view.call`` halves
    that the server baked into the approval request's markdown so
    the operator can see WHAT they're being asked to approve. The
    action buttons live on :class:`_ApprovalCard` (inline below the
    transcript) — keeping them out of the card prevents the "scroll
    up to find the buttons" issue on long tool cards with diffs /
    code blocks.

    Mirrors the structure of the in-proc
    :class:`ApprovalRequestContent` from
    ``src/inspect_ai/approval/_human/panel.py`` — content only,
    no actions.
    """

    DEFAULT_CSS = """
    _ApprovalContent {
        height: auto;
        padding-left: 2;
        margin-bottom: 1;
    }
    _ApprovalContent .approval-content {
        height: auto;
        margin-bottom: 1;
    }
    /* Variant for the block IMMEDIATELY BEFORE a separator: drop
     * the bottom margin so the rule sits flush against the
     * previous block's content. Pair-matched with
     * ``.approval-separator`` (zero margins) — together they make
     * the divider read as a tight transition, not a buffered one. */
    _ApprovalContent .approval-content-tight {
        height: auto;
        margin-bottom: 0;
    }
    /* The separator block (a horizontal rule) IS the visual divider
     * between view.context and view.call — wrapping it in the
     * standard margin-bottom: 1 wrapper would double-space the rule
     * (one blank below the previous block AND one below the rule),
     * pushing the next heading two rows below the divider. Render
     * tight: no top or bottom margin around the rule itself. */
    _ApprovalContent .approval-separator {
        height: auto;
        margin: 0;
    }
    """

    def __init__(self, state: ToolCallState) -> None:
        super().__init__()
        self._state = state

    def compose(self) -> ComposeResult:
        pending = self._state.pending_approval
        if pending is None:
            # Defensive: the parent only mounts us while pending is
            # set, but a fast race could see it cleared. Yield nothing.
            return
        # No "⚠ approval requested" intro line: the lifecycle pill
        # in the session header already says "awaiting approval"
        # and the composer bar below is the obvious call to action.
        #
        # Content area: same renderer as the tool card body. The
        # server's ``_build_request`` baked bold view titles + a
        # horizontal-rule block between view.context and view.call
        # into the markdown text, so the visual structure of the
        # in-proc ``ApprovalPanel`` falls out for free.
        blocks = list(pending.request.tool_call.content or [])
        for i, block in enumerate(blocks):
            # Three wrapper classes:
            # - ``approval-separator``: the rule itself, zero margin.
            # - ``approval-content-tight``: a normal block whose
            #   NEXT sibling is the separator. Drop the bottom
            #   margin so the rule sits flush against this block's
            #   content (otherwise the standard 1-row margin would
            #   put a blank row above the divider).
            # - ``approval-content``: standard block with the usual
            #   1-row bottom margin separating it from the next.
            if _is_separator_block(block):
                # Custom render — same dotted-leader Rule the in-proc
                # ``ApprovalPanel`` uses (see ``render_tool_approval``
                # in ``approval/_human/util.py``). The wire still
                # carries ``---`` so non-TUI clients (Zed et al.)
                # render a standard markdown horizontal rule; the
                # nicer dotted style is purely a TUI flourish.
                with Vertical(classes="approval-separator"):
                    yield _approval_separator_widget()
                continue
            if i + 1 < len(blocks) and _is_separator_block(blocks[i + 1]):
                wrapper_class = "approval-content-tight"
            else:
                wrapper_class = "approval-content"
            with Vertical(classes=wrapper_class):
                yield from compose_content_item(
                    block, context_id=self._state.tool_call_id
                )


# Post-resolution approval text + colour, appended to the tool's
# header row (see ``ToolCallWidget._header_text``). Keeping the
# decision inline on the same line as the duration / status glyph
# is more compact than a separate summary widget AND groups the
# whole tool-call outcome (it ran AND the operator approved it) in
# one anchor.
def _approval_separator_widget() -> Static:
    """Dotted-leader rule, matching the in-proc ``ApprovalPanel``.

    The in-proc panel renders the divider between ``view.context``
    and ``view.call`` with Rich's ``Rule`` using a one-dot-leader
    character (``U+2024``) and a subtle dark-grey style — see
    ``render_tool_approval`` in ``approval/_human/util.py``. Mirror
    that exact shape here so the inline approval card reads with
    the same visual restraint.

    The wire payload still carries ``---`` (markdown horizontal
    rule) so non-TUI ACP clients render a standard rule; the dotted
    leader is a TUI-side flourish that doesn't require any protocol
    extension.
    """
    from rich.rule import Rule

    return Static(Rule("", style="#282c34", align="left", characters="․"))


_DECISION_TEXT: dict[ApprovalDecisionLabel, str] = {
    "approved": "approved by you",
    "denied": "denied by you",
    "cancelled": "cancelled",
}

_DECISION_COLOR: dict[ApprovalDecisionLabel, str] = {
    "approved": "$success",
    "denied": "$error",
    "cancelled": "$warning",
}
