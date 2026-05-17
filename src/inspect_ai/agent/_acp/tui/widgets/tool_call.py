"""Tool-call card widget — renders one :class:`ToolCallState`.

Composition (matches :class:`MessageWidget`'s bullet + indented-body
layout so tool calls read as another row in the conversation, not a
visually distinct card):

- Header: coloured bullet + tool name + dim args.
- Body: indented under the tool name (``padding-left: 2``). Per
  content variant — text content blocks, native
  :class:`FileEditToolCallContent` diff, terminal placeholder.
- Footer: status glyph (✓/✗/spinner) + client-derived duration, also
  indented under the tool name.

Status is carried by the footer glyph alone — no border colour — to
match the calmer, flush layout the message widget uses.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai._util.rich import clean_control_characters

from ..state import ToolCallState
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

_COMPLETED_GLYPH = "✓"
_FAILED_GLYPH = "✗"

# Bullet colour for the tool-call header — single static colour so the
# tool-call header reads as a "row in the conversation" (parallel to
# the role bullets on MessageWidget). Status info is carried by the
# footer glyph (✓/✗/spinner) instead of the bullet, the same way
# MessageWidget keeps its role colour static and lets the chip's
# spinner reflect pending state. Hex chosen as a Tokyo-Night-ish cyan
# so tools read distinctly from the system / assistant blue.
_TOOL_BULLET_COLOR = "#7dcfff"

_PLACEHOLDER_SIG: tuple[Any, ...] = ("placeholder",)


class ToolCallWidget(Widget):
    """Bullet-prefixed tool-call row, matched to :class:`MessageWidget`.

    No border: the colour-coded bullet (cyan) plus body indentation
    are the only structural cues. Status info lives in the footer
    glyph (✓/✗/spinner), not in chrome around the card.
    """

    DEFAULT_CSS = """
    ToolCallWidget {
        height: auto;
        /* padding-bottom: 1 (not margin-bottom) is the *only* source
         * of trailing space below the footer:
         *   - It replaces the row the old card border occupied, so
         *     content doesn't look truncated.
         *   - Being internal, it never gets clipped by VerticalScroll
         *     when the tool call is the last transcript item.
         *   - And because there's no margin-bottom on top of it, the
         *     gap to the next message / tool / composer comes from
         *     one source instead of two stacking to a 2-row gap.
         * (MessageWidget achieves the same single-row gap via its
         * margin-bottom — but messages aren't followed by a chrome
         * element like a footer, so the clipping risk doesn't bite.) */
        padding: 0 2 1 2;
    }
    /* padding-bottom: 1 gives the title row a blank line below it
     * before the first body item (code block / output / plan), so
     * the header reads as a heading instead of running into the
     * body content. */
    ToolCallWidget .header {
        height: auto;
        padding-bottom: 1;
    }
    /* Body + footer share the role-word indent so everything below
     * the bullet visually lines up under the *tool name* rather than
     * the bullet itself — parallel to MessageWidget's `.body`
     * padding-left. */
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
    ToolCallWidget .footer {
        color: $text-muted;
        height: auto;
        padding-left: 2;
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
    """

    def __init__(self, state: ToolCallState) -> None:
        super().__init__()
        self._state = state
        # In-flight spinner frame, advanced by ``tick_duration``. Same
        # cadence as the assistant chip spinner (driven by the
        # SessionScreen's periodic timer).
        self._spinner_frame = 0
        # Snapshots of what's currently MOUNTED. update_state diffs
        # against these rather than the live state (which mutates in
        # place inside SessionState._merge_tool_fields) so we can
        # detect what actually changed and apply minimal DOM updates.
        self._mounted_header = self._header_text()
        self._mounted_footer = self._footer_text()
        self._mounted_status = self._state.status
        self._mounted_kind: str = "plan" if self._is_plan_state() else "content"
        self._mounted_item_sigs: list[tuple[Any, ...]] = self._compute_item_sigs()
        self._refresh_status_class()

    # ------------------------------------------------------------------
    # Compose + initial render
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes="header", markup=True)
        with Vertical(classes="body"):
            yield from self._compose_body()
        yield Static(self._footer_text(), classes="footer", markup=False)

    def _refresh_status_class(self) -> None:
        for cls in ("in-flight", "completed", "failed"):
            self.remove_class(cls)
        if self._state.status == "failed":
            self.add_class("failed")
        elif self._state.status == "completed":
            self.add_class("completed")
        else:
            self.add_class("in-flight")

    # ------------------------------------------------------------------
    # Periodic tick — keeps in-flight spinner + elapsed advancing
    # ------------------------------------------------------------------

    def tick_duration(self) -> None:
        """Refresh just the footer so the in-flight elapsed + spinner advance.

        Called by the SessionScreen's periodic tick — terminal states
        already show the final glyph + duration so we skip them and
        avoid needless DOM churn.
        """
        if self._state.is_terminal:
            return
        self._spinner_frame += 1
        try:
            self.query_one(".footer", Static).update(self._footer_text())
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # State update — diff mounted vs. incoming and apply minimal patch
    # ------------------------------------------------------------------

    def update_state(self, state: ToolCallState) -> None:
        """Re-bind to (possibly mutated) state and apply minimal updates.

        Critical for live visual quality: a wholesale-rebuild on every
        notification flashed every tool card whenever any chunk
        arrived. This implementation diffs against the mounted
        snapshot and only touches what changed.

        Update strategy, applied top-to-bottom:

        - Header / footer / status border — cheap re-render only when
          their text changed.
        - Body items — gated on a fingerprint diff. When the body must
          change, pick exactly one of: wholesale rebuild, extend last
          item in place, or append-only mount. Fall back to wholesale
          rebuild when the diff doesn't fit those shapes.
        """
        self._state = state

        self._update_status_class_if_changed()
        self._update_header_if_changed()
        self._update_footer_if_changed()

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
        if self._state.status != self._mounted_status:
            self._refresh_status_class()
            self._mounted_status = self._state.status

    def _update_header_if_changed(self) -> None:
        new_header = self._header_text()
        if new_header == self._mounted_header:
            return
        try:
            self.query_one(".header", Static).update(new_header)
        except NoMatches:
            pass
        self._mounted_header = new_header

    def _update_footer_if_changed(self) -> None:
        new_footer = self._footer_text()
        if new_footer == self._mounted_footer:
            return
        try:
            self.query_one(".footer", Static).update(new_footer)
        except NoMatches:
            pass
        self._mounted_footer = new_footer

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

        Triggers: kind switch (plan ↔ content), any change inside a
        plan body (plans are short and rebuild cheaply), or a
        transition into / out of the empty ``(no output yet)``
        placeholder.
        """
        if new_kind != self._mounted_kind:
            return True
        if new_kind == "plan":
            return True
        was_placeholder = self._mounted_item_sigs == [_PLACEHOLDER_SIG]
        is_placeholder = new_sigs == [_PLACEHOLDER_SIG]
        return was_placeholder or is_placeholder

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
        if not items:
            yield Static("(no output yet)", classes="body-content", markup=False)
            return
        # Each content item lives in its own ``.content-item`` wrapper
        # so update_state can identify "the widget for item N" and
        # append-only mount new wrappers without disturbing existing
        # ones. Wrapping is what eliminates the flash you'd otherwise
        # get from tearing the whole body down on every progress.
        for item in items:
            with Vertical(classes="content-item"):
                yield from self._compose_item(item)

    def _compose_item(self, item: object) -> ComposeResult:
        type_name = getattr(item, "type", None)
        if type_name == "diff":
            yield from self._compose_diff(item)
            return
        if type_name == "terminal":
            terminal_id = getattr(item, "terminal_id", "?")
            yield Static(
                f"[terminal: {terminal_id}]", classes="body-content", markup=False
            )
            return
        if type_name == "content":
            inner = getattr(item, "content", None)
            text = self._text_for_inner(inner)
            if not text:
                yield Static("", classes="body-content", markup=False)
                return
            # Clean control characters first — untrusted tool stdout
            # can include ANSI escapes / NUL bytes that confuse rich's
            # measurement pass (same util the rich display uses).
            cleaned = clean_control_characters(text)
            # CollapsibleContent handles its own truncation +
            # click-to-expand. Body rendered via StyledMarkdown so
            # fenced code is syntax-highlighted vs plain stdout.
            yield CollapsibleContent(cleaned, max_lines=_DEFAULT_TOOL_OUTPUT_MAX_LINES)
            return
        # Unknown content type — log so a router-side bug surfaces
        # instead of being silently swallowed. Still emit a placeholder
        # so the card stays renderable.
        logger.warning(
            "ToolCallWidget: unknown content item type %r on tool_call_id=%s",
            type_name,
            self._state.tool_call_id,
        )
        yield Static(
            f"[{type_name or 'unknown'}]", classes="body-content", markup=False
        )

    def _compose_diff(self, item: object) -> ComposeResult:
        path = getattr(item, "path", "?")
        old_text = getattr(item, "old_text", None)
        new_text = getattr(item, "new_text", "") or ""
        yield Static(f"--- {path}", classes="diff-header", markup=False)
        if old_text:
            for line in old_text.splitlines() or [""]:
                yield Static(f"- {line}", classes="diff-old", markup=False)
        for line in new_text.splitlines() or [""]:
            yield Static(f"+ {line}", classes="diff-new", markup=False)

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
        # Trailing blank row so the footer doesn't press against the
        # last plan entry — CollapsibleContent does this via its own
        # margin-bottom, but the plan path bypasses that widget.
        yield Static("", classes="plan-spacer", markup=False)

    # ------------------------------------------------------------------
    # Per-state derivations — header, footer, plan / fingerprint shape
    # ------------------------------------------------------------------

    def _header_text(self) -> str:
        """Header: coloured bullet + bold tool name + dim args.

        Mirrors :meth:`MessageWidget._chip_text` — coloured bullet on
        the left so the eye reads tool calls as another row in the
        conversation, with the body indented under the *tool name*
        rather than the bullet.

        The router formats ``title`` via
        :func:`inspect_ai.agent._acp.tool_content.descriptive_title` —
        e.g. ``bash ls /usr/bin`` or ``update_plan``. Splitting on the
        first space recovers ``name`` vs argument summary so the eye
        lands on the *tool* first. We can't call ``descriptive_title``
        directly here: the TUI only receives the post-formatted string
        on the wire, not the raw ``(fn, arguments)`` pair the function
        needs.
        """
        fg = _TOOL_BULLET_COLOR
        title = self._state.title or self._state.tool_call_id
        name, _, args = title.partition(" ")
        # Escape brackets in args so any ``[…]`` inside a path or URL
        # isn't interpreted as Rich markup.
        if args:
            args_escaped = args.replace("[", r"\[").replace("]", r"\]")
            return f"[{fg}]•[/] [bold]{name}[/bold] [dim]{args_escaped}[/dim]"
        return f"[{fg}]•[/] [bold]{name}[/bold]"

    def _footer_text(self) -> str:
        # Status reads as a single glyph: animated spinner while in
        # flight, ✓ on success, ✗ on failure. Border colour already
        # carries the redundant status signal so the glyph + duration
        # is enough text to scan.
        if self._state.status == "completed":
            glyph = _COMPLETED_GLYPH
        elif self._state.status == "failed":
            glyph = _FAILED_GLYPH
        else:
            glyph = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
        # In-flight: derive elapsed from start_time so the card surfaces
        # progress without waiting for a terminal status, and append a
        # quiet "(esc to interrupt)" hint so the operator knows the
        # action is available without having to scan the footer keymap.
        if self._state.is_terminal:
            return f"{glyph} {format_duration(self._state.duration_seconds)}"
        duration = format_duration(time.monotonic() - self._state.start_time)
        return f"{glyph} {duration} (esc to interrupt)"

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
        if not items:
            return [_PLACEHOLDER_SIG]
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
