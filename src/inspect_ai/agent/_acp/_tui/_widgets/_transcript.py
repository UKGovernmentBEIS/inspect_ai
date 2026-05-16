"""Scrollable transcript container — mounts message + tool-call widgets.

Driven by :class:`SessionState`. Re-syncing is incremental: new items
mount, existing items update or remount based on a small fingerprint
so streaming-text chunks within a message visibly extend without
churning the whole transcript. Auto-scrolls to bottom on new items
when the user was already at the bottom — preserves manual scroll-back
without losing live-tail.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget

from .._state import MessageGroup, SessionState, ToolCallState
from ._message import MessageWidget
from ._tool_call import ToolCallWidget


def _message_fingerprint(group: MessageGroup) -> tuple[int, int, str]:
    """Detect message content changes cheaply.

    ``(segment_count, last_segment_len, model)`` covers all the
    streaming mutations Phase 2 cares about: chunks extending the last
    segment (len changes), a new segment starting (count changes), and
    a later chunk supplying ``_meta["inspect.model"]`` for the first
    time (model changes).
    """
    last_len = len(group.segments[-1].text) if group.segments else 0
    return (len(group.segments), last_len, group.model or "")


class TranscriptWidget(VerticalScroll):
    """Scrollable list of message + tool-call widgets in arrival order."""

    DEFAULT_CSS = """
    TranscriptWidget {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Map item identity → (widget, fingerprint). The fingerprint is
        # only used for MessageGroup; tool-call cards mutate in place
        # via update_state.
        self._entries: dict[str, tuple[Widget, object]] = {}

    def refresh_from(self, state: SessionState) -> None:
        """Sync mounted widgets to ``state.items`` order + content."""
        at_bottom = self._is_at_bottom()
        existing_keys = set(self._entries.keys())
        seen_keys: set[str] = set()
        mounted_anything = False

        for item in state.items:
            key = self._key_for(item)
            seen_keys.add(key)
            entry = self._entries.get(key)
            if entry is None:
                widget = self._build_widget(item, state)
                self._entries[key] = (widget, self._fingerprint(item))
                self.mount(widget)
                mounted_anything = True
                continue
            widget, old_fp = entry
            new_fp = self._fingerprint(item)
            if isinstance(item, ToolCallState) and isinstance(widget, ToolCallWidget):
                widget.update_state(item)
                self._entries[key] = (widget, new_fp)
            elif isinstance(item, MessageGroup) and new_fp != old_fp:
                # Remount the message widget so the new segment / text
                # extension renders. Position is preserved by mounting
                # at the same index in the scroll's children list.
                self._remount_message(key, item, state, widget)

        for stale in existing_keys - seen_keys:
            entry = self._entries.pop(stale, None)
            if entry is not None:
                try:
                    entry[0].remove()
                except Exception:
                    pass

        if mounted_anything and at_bottom:
            self.call_after_refresh(self.scroll_end, animate=False)

    def _remount_message(
        self,
        key: str,
        item: MessageGroup,
        state: SessionState,
        old_widget: Widget,
    ) -> None:
        # Find the old widget's index so the new widget lands in the
        # same slot — order in items[] is authoritative.
        try:
            index = self.children.index(old_widget)
        except ValueError:
            index = -1
        try:
            old_widget.remove()
        except Exception:
            pass
        new_widget = self._build_widget(item, state)
        if index >= 0:
            self.mount(new_widget, before=index if index < len(self.children) else None)
        else:
            self.mount(new_widget)
        self._entries[key] = (new_widget, self._fingerprint(item))

    @staticmethod
    def _fingerprint(item: MessageGroup | ToolCallState) -> object:
        if isinstance(item, MessageGroup):
            return _message_fingerprint(item)
        # Tool calls update in place; the fingerprint is unused beyond
        # being non-None so the equality check above falls through.
        return item.status

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
        """Nudge in-flight tool cards so their elapsed footer advances.

        Called from the SessionScreen's periodic timer — terminal cards
        skip the update inside :meth:`ToolCallWidget.tick_duration`, so
        this is cheap once a tool completes.
        """
        for entry in self._entries.values():
            widget, _ = entry
            if isinstance(widget, ToolCallWidget):
                widget.tick_duration()
