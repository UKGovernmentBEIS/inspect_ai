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

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from .._state import ToolCallState

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
    "other": "•",
    None: "•",
}

_STATUS_LABELS: dict[str, str] = {
    "pending": "pending",
    "in_progress": "running",
    "completed": "completed",
    "failed": "failed",
}


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
        margin: 1 2;
        padding: 0 1;
        border: round $primary 40%;
    }
    ToolCallWidget.in-flight { border: round $warning; }
    ToolCallWidget.completed { border: round $success 60%; }
    ToolCallWidget.failed { border: round $error; }
    ToolCallWidget .header { text-style: bold; padding-bottom: 1; }
    ToolCallWidget .footer {
        color: $text-muted;
        padding-top: 1;
    }
    ToolCallWidget .diff-header {
        color: $text-muted;
        text-style: italic;
    }
    ToolCallWidget .diff-old { color: $error; }
    ToolCallWidget .diff-new { color: $success; }
    ToolCallWidget .body-content { padding-left: 1; }
    """

    def __init__(self, state: ToolCallState) -> None:
        super().__init__()
        self._state = state
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
        yield Static(self._header_text(), classes="header", markup=False)
        with Vertical(classes="body"):
            yield from self._compose_body()
        yield Static(self._footer_text(), classes="footer", markup=False)

    def _header_text(self) -> str:
        icon = _KIND_ICONS.get(self._state.kind, _KIND_ICONS[None])
        title = self._state.title or self._state.tool_call_id
        return f"{icon} {title}"

    def _compose_body(self) -> ComposeResult:
        items = self._state.content or []
        if not items:
            yield Static("(no output yet)", classes="body-content", markup=False)
            return
        for item in items:
            yield from self._compose_item(item)

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
            yield Static(
                self._text_for_inner(inner), classes="body-content", markup=False
            )
        else:
            # Unknown variant — show the raw type marker so we notice.
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
        """Re-bind to a (possibly new) state and re-render in place.

        Cheaper than recreating the widget — the transcript container
        prefers this when a ToolCallProgress arrives for a card that's
        already mounted.
        """
        self._state = state
        self._refresh_status_class()
        try:
            self.query_one(".header", Static).update(self._header_text())
            self.query_one(".footer", Static).update(self._footer_text())
        except Exception:
            pass
        # Body is recomposed wholesale — content REPLACES per ACP
        # semantics (see _state._merge_tool_fields), so it's correct to
        # blow away and rebuild.
        try:
            body = self.query_one(".body", Vertical)
            for child in list(body.children):
                child.remove()
            for w in self._compose_body():
                body.mount(w)
        except Exception:
            pass
