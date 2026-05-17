"""Scrollable transcript container — mounts message + tool-call widgets.

Driven by :class:`SessionState`. Re-syncing is incremental: new items
mount, existing items update IN PLACE via their own ``update_state``
so streaming-text chunks within a message visibly extend without
churning the whole transcript. Auto-scrolls to bottom on new items
when the user was already at the bottom — preserves manual scroll-back
without losing live-tail.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget

from ..state import MessageGroup, SessionState, ToolCallState
from .message import MessageWidget
from .tool_call import ToolCallWidget, tool_state_fingerprint


def _message_fingerprint(
    group: MessageGroup,
) -> tuple[int, int, str, bool, int]:
    """Detect message content changes cheaply.

    Captures all the streaming mutations Phase 2 cares about: chunks
    extending the last segment (len changes), a new segment starting
    (count changes), a later chunk supplying ``_meta["inspect.model"]``
    for the first time (model changes), the pending → completed flip
    (so the chip's spinner-or-dot indicator can re-render even when no
    content arrived), AND the retry counter (so a collapsed retry on
    an existing group triggers a chip re-render).
    """
    last_len = len(group.segments[-1].text) if group.segments else 0
    return (
        len(group.segments),
        last_len,
        group.model or "",
        group.pending,
        group.retries,
    )


class TranscriptWidget(VerticalScroll):
    """Scrollable list of message + tool-call widgets in arrival order."""

    DEFAULT_CSS = """
    TranscriptWidget {
        height: 1fr;
        /* Hide the scrollbar gutter so transcript content reaches the
         * right edge. Wheel + keyboard scrolling still work; the
         * scrollbar just doesn't reserve a column. */
        scrollbar-size: 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Map item identity → (widget, fingerprint). Both message and
        # tool-call widgets update in place; the fingerprint just
        # detects whether anything changed so we know to nudge the
        # auto-scroll.
        self._entries: dict[str, tuple[Widget, object]] = {}

    def refresh_from(self, state: SessionState) -> None:
        """Sync mounted widgets to ``state.items`` order + content."""
        at_bottom = self._is_at_bottom()
        existing_keys = set(self._entries.keys())
        seen_keys: set[str] = set()
        content_changed = False

        for item in state.items:
            key = self._key_for(item)
            seen_keys.add(key)
            entry = self._entries.get(key)
            if entry is None:
                widget = self._build_widget(item, state)
                self._entries[key] = (widget, self._fingerprint(item))
                self.mount(widget)
                content_changed = True
                continue
            widget, old_fp = entry
            new_fp = self._fingerprint(item)
            if isinstance(item, ToolCallState) and isinstance(widget, ToolCallWidget):
                # Gate on fingerprint change — the comprehensive
                # tool-call fingerprint (status + content + raw_input)
                # now catches every visible mutation, so the widget
                # only re-renders when something actually changed.
                # Mirrors the message branch below.
                if old_fp != new_fp:
                    widget.update_state(item)
                    self._entries[key] = (widget, new_fp)
                    content_changed = True
            elif isinstance(item, MessageGroup) and isinstance(widget, MessageWidget):
                # IN-PLACE update — extends the last segment or mounts
                # new segments rather than tearing the bubble down.
                # Avoids the visible flash a full remount would cause
                # on every streaming chunk.
                if old_fp != new_fp:
                    widget.update_state(item)
                    self._entries[key] = (widget, new_fp)
                    content_changed = True

        for stale in existing_keys - seen_keys:
            entry = self._entries.pop(stale, None)
            if entry is not None:
                try:
                    entry[0].remove()
                except Exception:
                    pass

        if content_changed and at_bottom:
            self.call_after_refresh(self.scroll_end, animate=False)

    @staticmethod
    def _fingerprint(item: MessageGroup | ToolCallState) -> object:
        if isinstance(item, MessageGroup):
            return _message_fingerprint(item)
        # Use the comprehensive tool-call fingerprint (status + title
        # + kind + content + raw_input) — not just status — so the
        # auto-scroll decision tracks live-tail tool output. Streaming
        # output that grows while status stays ``in_progress`` would
        # otherwise update the card silently without scrolling.
        return tool_state_fingerprint(item)

    def _build_widget(
        self, item: MessageGroup | ToolCallState, state: SessionState
    ) -> Widget:
        if isinstance(item, MessageGroup):
            return MessageWidget(item, current_model=state.current_model)
        return ToolCallWidget(item)

    @staticmethod
    def _key_for(item: MessageGroup | ToolCallState) -> str:
        if isinstance(item, MessageGroup):
            return f"msg:{item.message_id}"
        return f"tool:{item.tool_call_id}"

    def _is_at_bottom(self) -> bool:
        try:
            return self.scroll_y >= self.max_scroll_y - 1
        except Exception:
            return True

    def tick_inflight_durations(self) -> None:
        """Nudge in-flight tool cards + empty message spinners.

        Called from the SessionScreen's periodic timer. Terminal tool
        cards no-op inside :meth:`ToolCallWidget.tick_duration`, and
        message widgets that already have content no-op inside
        :meth:`MessageWidget.tick_spinner` — so this is cheap once
        everything's done animating.
        """
        for entry in self._entries.values():
            widget, _ = entry
            if isinstance(widget, ToolCallWidget):
                widget.tick_duration()
            elif isinstance(widget, MessageWidget):
                widget.tick_spinner()
