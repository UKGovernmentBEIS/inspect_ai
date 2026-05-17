"""Tool-call card widget — renders one :class:`ToolCallState`.

Composition:

- Header: kind icon + tool title
- Body: per content variant (text content blocks, native
  :class:`FileEditToolCallContent` diff, terminal placeholder)
- Footer: status chip + client-derived duration

The card border colour propagates from the session status pill: teal
while in-flight, sage on success, rust on failure (Phase 2 keeps the
"in-flight tint follows pill" behaviour the design doc calls out).
"""

from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai._util.rich import clean_control_characters
from inspect_ai._util.text import truncate_lines

from ..state import ToolCallState
from .markdown import StyledMarkdown

_DEFAULT_TOOL_OUTPUT_MAX_LINES = 15
"""How many lines of tool output to show before truncating.

Long bash outputs / file dumps blow out the transcript otherwise. The
trailing ``[+N more lines]`` indicator tells the operator something
was elided; Phase 6 will wire ^E to expand the body in place.
"""

_KIND_ICONS: dict[str | None, str] = {
    "read": "📄",
    "edit": "✎",
    "search": "⌕",
    "fetch": "↓",
    "delete": "✕",
    "move": "→",
    "execute": "▶",
    "think": "◆",
    "switch_mode": "⇄",
    # Unknown / generic kinds get no glyph — the tool name itself
    # carries enough signal in the header and a bullet was just
    # adding visual noise to most cards.
    "other": "",
    None: "",
}

_STATUS_LABELS: dict[str, str] = {
    "pending": "pending",
    "in_progress": "running",
    "completed": "completed",
    "failed": "failed",
}


def _item_signature(item: object) -> tuple[Any, ...]:
    """Module-level item fingerprint — shared with the transcript layer.

    Same shape as ``ToolCallWidget._item_signature`` (which delegates
    here). Lives at module scope so the TranscriptWidget can compute
    a comprehensive tool-call fingerprint without instantiating a
    widget, so its content-change detection scrolls live-tail
    correctly even while status stays ``in_progress``.
    """
    type_name = getattr(item, "type", None)
    if type_name == "content":
        inner = getattr(item, "content", None)
        text = getattr(inner, "text", "") if inner is not None else ""
        return ("content", len(text or ""), hash(text or ""))
    if type_name == "diff":
        old_text = getattr(item, "old_text", "") or ""
        new_text = getattr(item, "new_text", "") or ""
        return (
            "diff",
            getattr(item, "path", ""),
            hash(old_text),
            hash(new_text),
        )
    if type_name == "terminal":
        return ("terminal", getattr(item, "terminal_id", ""))
    return (type_name or "unknown",)


def tool_state_fingerprint(state: "ToolCallState") -> tuple[Any, ...]:
    """Comprehensive change signature for a ToolCallState.

    Returns a hashable tuple that changes whenever ANYTHING the user
    would see changes: status, title, kind, the list of content items
    (with text hashes so same-length replacements register), and the
    raw_input shape (plan-style tools render from raw_input not
    content). The transcript layer uses this to gate the auto-scroll
    decision so live-tail follows in-progress tool output.
    """
    content_sig = tuple(_item_signature(item) for item in (state.content or []))
    # raw_input shape matters for plan-style tools which render their
    # body from it. Use repr — it's stable for the dict shapes Inspect
    # produces and avoids importing the plan-extraction logic here.
    raw_input_sig: object
    if isinstance(state.raw_input, dict):
        raw_input_sig = hash(repr(sorted(state.raw_input.items(), key=str)))
    else:
        raw_input_sig = repr(state.raw_input)
    return (
        state.status,
        state.title or "",
        state.kind or "",
        content_sig,
        raw_input_sig,
    )


class _CollapsibleContent(Widget):
    """Truncated tool output that expands on click of the more-lines note.

    Renders ``max_lines`` of text via :class:`StyledMarkdown` plus, when
    the source was longer, a clickable underlined ``… N more lines``
    indicator. Clicking the indicator swaps the body for the full text
    and removes the note — one-way (no collapse back; once you've
    asked to see the rest you want to keep seeing it).

    The note carries an underline + hover tint to telegraph that it's
    interactive — the usual TUI convention for "this is clickable".
    """

    DEFAULT_CSS = """
    /* No margin here — the parent (ToolCallWidget puts margin-bottom
     * on the ``.content-item`` wrapper; MessageWidget mounts these
     * directly into a body Vertical). Inner margins on a widget
     * inside a height-auto Vertical wrapper don't reliably push
     * siblings apart, which caused blocks to render flush against
     * each other (no input/output separation). */
    _CollapsibleContent { height: auto; }
    _CollapsibleContent .body-content { height: auto; }
    /* Truncation note styling lives on the widget itself (not on the
     * parent) so the affordance reads consistently whether
     * _CollapsibleContent is mounted inside a tool card or a message
     * bubble. Underlined + muted telegraphs "click to expand"; hover
     * tint mirrors the usual TUI clickable convention. */
    _CollapsibleContent .truncation-note {
        color: $text-muted;
        text-style: italic underline;
        height: auto;
    }
    _CollapsibleContent .truncation-note:hover { color: $accent; }
    """

    def __init__(self, full_text: str, *, max_lines: int) -> None:
        super().__init__()
        self._full_text = full_text
        self._max_lines = max_lines
        self._expanded = False

    def compose(self) -> ComposeResult:
        shown, omitted = truncate_lines(self._full_text, max_lines=self._max_lines)
        yield Static(StyledMarkdown(shown), classes="body-content", id="cc-body")
        if omitted is not None and omitted > 0:
            label = f"… {omitted} more line{'s' if omitted != 1 else ''}"
            yield Static(label, classes="truncation-note", id="cc-note", markup=False)

    def on_click(self) -> None:
        # The body content rarely has interactive children, so any
        # click within this widget — note or body — counts as a
        # request to expand. Cheaper than per-widget click handlers
        # and avoids the empty-region miss most users would hit when
        # trying to click a 1-row italic note.
        if self._expanded:
            return
        self._expanded = True
        try:
            self.query_one("#cc-body", Static).update(StyledMarkdown(self._full_text))
        except Exception:
            return
        try:
            self.query_one("#cc-note", Static).remove()
        except Exception:
            pass

    def replace_text(self, text: str) -> None:
        """Replace the underlying text in place — for streaming tail growth.

        ToolCallWidget calls this when a ToolCallProgress extends the
        last content item rather than appending a new one. Updating
        the body text + truncation note avoids a full re-mount that
        would flash the surrounding card.
        """
        self._full_text = text
        try:
            body_static = self.query_one("#cc-body", Static)
        except Exception:
            return
        if self._expanded:
            body_static.update(StyledMarkdown(self._full_text))
            return
        shown, omitted = truncate_lines(self._full_text, max_lines=self._max_lines)
        body_static.update(StyledMarkdown(shown))
        # Note may or may not exist yet — recreate it conditionally so
        # late-arriving truncation (text grew past the limit) gets a
        # clickable expander.
        existing_note: Static | None = None
        try:
            existing_note = self.query_one("#cc-note", Static)
        except Exception:
            existing_note = None
        if omitted is not None and omitted > 0:
            label = f"… {omitted} more line{'s' if omitted != 1 else ''}"
            if existing_note is None:
                self.mount(
                    Static(
                        label,
                        classes="truncation-note",
                        id="cc-note",
                        markup=False,
                    )
                )
            else:
                existing_note.update(label)
        elif existing_note is not None:
            existing_note.remove()


def _format_duration(seconds: float | None) -> str:
    """Format duration the same way the picker formats running times.

    Sub-second durations land on most tool calls, so add a 1-decimal
    ``0.2s`` floor; minute/hour rolls match :func:`_format_running` so
    the eye reads card durations and picker times consistently.
    """
    if seconds is None:
        return "—"
    if seconds < 1.0:
        return f"{seconds:.1f}s"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m, s = divmod(total, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}m"


class ToolCallWidget(Widget):
    """Bordered card showing one tool call."""

    DEFAULT_CSS = """
    ToolCallWidget {
        height: auto;
        margin: 0 2 1 2;
        padding: 0 1;
        border: round $primary 40%;
    }
    ToolCallWidget.in-flight { border: round $warning 60%; }
    ToolCallWidget.completed { border: round $success 50%; }
    ToolCallWidget.failed { border: round $error; }
    ToolCallWidget .header {
        height: auto;
        padding-bottom: 1;
    }
    ToolCallWidget .body { height: auto; }
    /* Visual separation between successive content items (input view
     * vs. result output, multiple result blocks, etc.). The wrapper
     * carries the margin so the gap reliably contributes to the
     * parent's height-auto layout — putting the margin on the inner
     * _CollapsibleContent collapsed and blocks rendered flush. */
    ToolCallWidget .content-item { height: auto; margin-bottom: 1; }
    ToolCallWidget .footer {
        color: $text-muted;
        height: auto;
    }
    /* Truncation-note styling is on _CollapsibleContent itself —
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
        # Snapshots of what's currently MOUNTED, so update_state can
        # diff against the actual DOM rather than the live state
        # (which mutates in place in `_merge_tool_fields`). Tracked at
        # per-item granularity so we can append-only mount new content
        # blocks instead of tearing the whole body down on each
        # ToolCallProgress — that wholesale rebuild was the visible
        # flash the user saw whenever new content arrived.
        self._mounted_header = self._header_text()
        self._mounted_footer = self._footer_text()
        self._mounted_status = self._state.status
        self._mounted_kind: str = "plan" if self._is_plan_state() else "content"
        self._mounted_item_sigs: list[tuple[Any, ...]] = self._compute_item_sigs()
        self._refresh_status_class()

    def _refresh_status_class(self) -> None:
        for cls in ("in-flight", "completed", "failed"):
            self.remove_class(cls)
        if self._state.status == "failed":
            self.add_class("failed")
        elif self._state.status == "completed":
            self.add_class("completed")
        else:
            self.add_class("in-flight")

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes="header", markup=True)
        with Vertical(classes="body"):
            yield from self._compose_body()
        yield Static(self._footer_text(), classes="footer", markup=False)

    # ------------------------------------------------------------------
    # Per-item fingerprints — drive append-only body updates
    # ------------------------------------------------------------------

    def _item_signature(self, item: object) -> tuple[Any, ...]:
        """Per-content-item fingerprint for diffing mounted vs. incoming.

        Tuples are keyed by ``type`` first so a type change forces a
        re-mount, then by the visible-content shape (text length, diff
        path + side lengths, terminal id). Ordinary tool output that
        REPLACES the previous progress with an extended copy will
        produce the same prefix here, letting us append-only without
        retearing.
        """
        # Delegate to the module-level helper so the transcript layer
        # and the widget agree on what counts as a change. Includes
        # the text hash so same-length replacements register.
        return _item_signature(item)

    def _compute_item_sigs(self) -> list[tuple[Any, ...]]:
        """Snapshot the current state's body items for later diffing.

        Plan-style tools render from ``raw_input`` not ``content``, so
        their snapshot is a single ``("plan", …)`` tuple — any change
        triggers a wholesale plan rebuild (plans are short and change
        less often than streamed output).
        """
        if self._is_plan_state():
            plan = self._extract_plan_entries() or []
            return [("plan", tuple(self._plan_entry_sig(e) for e in plan))]
        items = self._state.content or []
        if not items:
            return [("placeholder",)]
        return [self._item_signature(item) for item in items]

    def _plan_entry_sig(self, entry: dict[str, Any]) -> tuple[str, str]:
        status = str(entry.get("status", "pending")).lower()
        text = str(
            entry.get("step")
            or entry.get("content")
            or entry.get("text")
            or entry.get("description")
            or entry.get("task")
            or ""
        )
        return (status, text)

    def _is_plan_state(self) -> bool:
        return self._extract_plan_entries() is not None

    def _header_text(self) -> str:
        """Header: optional icon + bold tool name + dim args.

        Inspect's router puts the tool name first in ``title`` (e.g.
        ``bash ls /usr/bin`` or just ``update_plan``). Splitting on the
        first space keeps name + arg-summary as separate visual
        weights so the eye lands on the *tool* before the parameters.
        Unmapped kinds get no glyph (the tool name carries the signal).
        """
        icon = _KIND_ICONS.get(self._state.kind, _KIND_ICONS[None])
        prefix = f"{icon} " if icon else ""
        title = self._state.title or self._state.tool_call_id
        name, _, args = title.partition(" ")
        # Escape brackets in args so any ``[…]`` inside a path or URL
        # isn't interpreted as Rich markup.
        if args:
            args_escaped = args.replace("[", r"\[").replace("]", r"\]")
            return f"{prefix}[bold]{name}[/bold] [dim]{args_escaped}[/dim]"
        return f"{prefix}[bold]{name}[/bold]"

    def _compose_body(self) -> ComposeResult:
        # Plan tools (update_plan, todo_write) carry the actual plan in
        # raw_input — the result content is usually just "Plan updated".
        # Render the entries as a checklist so the operator can see what
        # the agent committed to.
        plan_entries = self._extract_plan_entries()
        if plan_entries:
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

    def _compose_plan(self, entries: list[dict[str, Any]]) -> ComposeResult:
        for entry in entries:
            status = str(entry.get("status", "pending")).lower()
            # Inspect's ``update_plan`` uses ``step``; other plan-style
            # tools may use ``content`` / ``text`` / ``description`` /
            # ``task``. Fall through to the first non-empty value so
            # the entry text always renders.
            text = str(
                entry.get("step")
                or entry.get("content")
                or entry.get("text")
                or entry.get("description")
                or entry.get("task")
                or ""
            )
            if status == "completed":
                glyph = "[x]"
            elif status == "in_progress":
                glyph = "[~]"
            else:
                glyph = "[ ]"
            # Render in normal text — the glyph alone communicates
            # status. Per-state colouring (green/yellow/muted) made the
            # whole panel read as a wall of green once items finished;
            # plain text is calmer and more legible.
            yield Static(f"  {glyph} {text}", classes="plan-entry", markup=False)
        # Trailing blank row so the footer ("completed · 0.0s") doesn't
        # press against the last plan entry — _CollapsibleContent does
        # this via its own margin-bottom, but the plan path bypasses
        # that widget.
        yield Static("", classes="plan-spacer", markup=False)

    def _compose_item(self, item: object) -> ComposeResult:
        type_name = getattr(item, "type", None)
        if type_name == "diff":
            yield from self._compose_diff(item)
        elif type_name == "terminal":
            terminal_id = getattr(item, "terminal_id", "?")
            yield Static(
                f"[terminal: {terminal_id}]", classes="body-content", markup=False
            )
        elif type_name == "content":
            inner = getattr(item, "content", None)
            text = self._text_for_inner(inner)
            if not text:
                yield Static("", classes="body-content", markup=False)
                return
            # Clean control characters first — untrusted tool stdout
            # can include ANSI escapes / NUL bytes that confuse rich's
            # measurement pass (same util the rich display uses).
            cleaned = clean_control_characters(text)
            # _CollapsibleContent handles its own truncation +
            # click-to-expand. Body rendered via StyledMarkdown so
            # fenced code is syntax-highlighted vs plain stdout.
            yield _CollapsibleContent(cleaned, max_lines=_DEFAULT_TOOL_OUTPUT_MAX_LINES)
        else:
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

    def _text_for_inner(self, inner: object) -> str:
        # TextContentBlock → text; everything else gets a placeholder
        # consistent with the message widget's handling.
        if inner is None:
            return ""
        if getattr(inner, "type", None) == "text":
            return getattr(inner, "text", "") or ""
        type_name = getattr(inner, "type", None) or "content"
        return f"[{type_name}]"

    def _footer_text(self) -> str:
        status = _STATUS_LABELS.get(self._state.status, self._state.status)
        # In-flight: derive elapsed from start_time so the card surfaces
        # progress without waiting for a terminal status.
        if self._state.is_terminal:
            duration = _format_duration(self._state.duration_seconds)
        else:
            duration = _format_duration(time.monotonic() - self._state.start_time)
        return f"{status} · {duration}"

    def tick_duration(self) -> None:
        """Refresh just the footer so the in-flight elapsed value advances.

        Called by the SessionScreen's periodic tick — terminal states
        already show the final duration so we skip them and avoid
        needless DOM churn.
        """
        if self._state.is_terminal:
            return
        try:
            self.query_one(".footer", Static).update(self._footer_text())
        except Exception:
            pass

    def update_state(self, state: ToolCallState) -> None:
        """Re-bind to (possibly mutated) state and apply minimal updates.

        Critical for live visual quality: the previous implementation
        wholesale-rebuilt the body on every notification, which
        flashed every tool card whenever ANY chunk arrived. This
        version diffs against the mounted snapshot and only touches
        what changed:

        - Header / footer / border class: cheap re-render only when
          their inputs changed (status, title, kind, in-flight elapsed).
        - Body items: append-only mount of new content wrappers when
          the existing prefix matches; in-place text replacement when
          the last item grew (streaming output); wholesale rebuild
          only on a structural change (rare — plan updates, content
          truncated, item type changed mid-stream).
        """
        self._state = state

        if state.status != self._mounted_status:
            self._refresh_status_class()
            self._mounted_status = state.status

        new_header = self._header_text()
        if new_header != self._mounted_header:
            try:
                self.query_one(".header", Static).update(new_header)
            except Exception:
                pass
            self._mounted_header = new_header

        new_footer = self._footer_text()
        if new_footer != self._mounted_footer:
            try:
                self.query_one(".footer", Static).update(new_footer)
            except Exception:
                pass
            self._mounted_footer = new_footer

        # Body diff — gate the expensive mount work on actual change.
        new_kind = "plan" if self._is_plan_state() else "content"
        new_sigs = self._compute_item_sigs()
        if new_kind == self._mounted_kind and new_sigs == self._mounted_item_sigs:
            return

        try:
            body = self.query_one(".body", Vertical)
        except Exception:
            return

        # Strategy:
        # - kind switch (plan ↔ content) or plan changed → wholesale rebuild
        # - placeholder ↔ real content transition → wholesale rebuild
        # - existing items unchanged + new items at end → append-only
        # - last existing item grew (text-content only) → in-place update,
        #   then append any further new items
        # - anything else (prefix mismatch, item type changed,
        #   item shrunk / removed) → wholesale rebuild
        old_sigs = self._mounted_item_sigs
        kind_switch = new_kind != self._mounted_kind
        was_placeholder = old_sigs == [("placeholder",)]
        is_placeholder = new_sigs == [("placeholder",)]
        if kind_switch or new_kind == "plan" or was_placeholder or is_placeholder:
            self._rebuild_body_wholesale(body)
            self._mounted_item_sigs = new_sigs
            self._mounted_kind = new_kind
            return

        # Content path: try append-only / extend-last.
        items = self._state.content or []
        common = self._common_prefix(old_sigs, new_sigs)
        # Tail-update case: same length, last item grew.
        if common == len(old_sigs) - 1 and len(new_sigs) == len(old_sigs):
            last_old = old_sigs[-1]
            last_new = new_sigs[-1]
            if (
                last_old[0] == "content"
                and last_new[0] == "content"
                and last_new[1] >= last_old[1]
            ):
                if self._extend_last_content_item(body, items[-1]):
                    self._mounted_item_sigs = new_sigs
                    return

        if common == len(old_sigs):
            # Pure append: existing prefix unchanged, mount the new tail.
            for item in items[common:]:
                wrapper = Vertical(classes="content-item")
                body.mount(wrapper)
                for w in self._compose_item(item):
                    wrapper.mount(w)
            self._mounted_item_sigs = new_sigs
            return

        # Anything else — fall back to wholesale rebuild. This is the
        # rare case (item type flipped, prefix changed, shrink); the
        # common streaming case is handled above without a rebuild.
        self._rebuild_body_wholesale(body)
        self._mounted_item_sigs = new_sigs

    @staticmethod
    def _common_prefix(old: list[tuple[Any, ...]], new: list[tuple[Any, ...]]) -> int:
        n = 0
        while n < len(old) and n < len(new) and old[n] == new[n]:
            n += 1
        return n

    def _extend_last_content_item(self, body: Vertical, item: object) -> bool:
        """Replace the last content wrapper's body text with the new text.

        Returns False if anything looks wrong (no wrapper, unexpected
        child shape) so the caller can fall back to wholesale rebuild.
        """
        children = list(body.children)
        if not children:
            return False
        last_wrapper = children[-1]
        if not isinstance(last_wrapper, Vertical):
            return False
        # The wrapper holds exactly one child for a "content" item: a
        # _CollapsibleContent. Anything else and we bail to the safe
        # rebuild path.
        inner_children = list(last_wrapper.children)
        if len(inner_children) != 1:
            return False
        cc = inner_children[0]
        if not isinstance(cc, _CollapsibleContent):
            return False
        text = self._text_for_inner(getattr(item, "content", None))
        if not text:
            return False
        cleaned = clean_control_characters(text)
        cc.replace_text(cleaned)
        return True

    def _rebuild_body_wholesale(self, body: Vertical) -> None:
        for child in list(body.children):
            child.remove()
        for w in self._compose_body():
            body.mount(w)
