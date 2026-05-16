"""Message widget — renders one :class:`MessageGroup`.

Two top-level variants by ``role``:

- ``user`` — left-aligned block with ``user · dataset_input`` chip.
- ``assistant`` — left-aligned block with the model chip (drawn from
  ``MessageGroup.model``, falling back to the session-wide current
  model when the group's own attribution is missing).

Reasoning segments (``kind == "reasoning"``) render as dimmed
sub-blocks with an expand/collapse toggle (bound to ``^E`` on the
focused widget). Phase 2 supports basic expand/collapse only — the
encrypted / redacted variants are Phase 6 work.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from .._state import MessageGroup, Segment


class _ReasoningBlock(Widget, can_focus=True):
    """Collapsible reasoning sub-block within an assistant message.

    Dim by default; ``^E`` toggles expand/collapse. Each block tracks
    its own state so multiple reasoning blocks in one assistant message
    can be expanded independently.
    """

    DEFAULT_CSS = """
    _ReasoningBlock {
        height: auto;
        padding: 0 0;
        color: $text-muted;
    }
    _ReasoningBlock .header { text-style: italic; }
    _ReasoningBlock .body { padding-left: 2; }
    _ReasoningBlock.collapsed .body { display: none; }
    _ReasoningBlock:focus > .header { text-style: italic underline; }
    """

    BINDINGS = [
        Binding("ctrl+e", "toggle_reasoning", "expand", show=False),
    ]

    def __init__(self, text: str, *, collapsed: bool = True) -> None:
        super().__init__()
        self._text = text
        self._collapsed = collapsed

    def compose(self) -> ComposeResult:
        glyph = "▸" if self._collapsed else "▾"
        yield Static(f"{glyph} reasoning", classes="header")
        yield Static(self._text, classes="body")
        if self._collapsed:
            self.add_class("collapsed")

    def action_toggle_reasoning(self) -> None:
        self._collapsed = not self._collapsed
        # Toggle the CSS class and re-render the header glyph.
        if self._collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")
        try:
            header = self.query_one(".header", Static)
            header.update(("▸" if self._collapsed else "▾") + " reasoning")
        except Exception:
            pass


class MessageWidget(Widget):
    """Renders one MessageGroup as user or assistant content."""

    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        padding: 1 2;
    }
    MessageWidget.user { color: $text; }
    MessageWidget.assistant { color: $text; }
    MessageWidget .chip {
        color: $text-muted;
        padding-bottom: 1;
    }
    MessageWidget.user .chip { color: $accent; }
    MessageWidget.assistant .chip { color: $success; }
    MessageWidget .segment-text { padding-bottom: 0; }
    """

    def __init__(
        self, group: MessageGroup, *, current_model: str | None = None
    ) -> None:
        super().__init__()
        self._group = group
        self._current_model = current_model
        self.add_class(group.role)

    def compose(self) -> ComposeResult:
        yield Static(self._chip_text(), classes="chip", markup=False)
        with Vertical():
            yield from self._compose_segments()

    def _chip_text(self) -> str:
        if self._group.role == "user":
            return "user · dataset_input"
        # Assistant: prefer the group's own model attribution; fall back
        # to the session's current model when the chunk had no
        # `_meta["inspect.model"]` (e.g. an old server).
        model = self._group.model or self._current_model or "—"
        return f"assistant · {model}"

    def _compose_segments(self) -> ComposeResult:
        # Empty group (no segments yet) still emits a row so the
        # bubble is visible while streaming starts.
        if not self._group.segments:
            yield Static("", classes="segment-text")
            return
        for seg in self._group.segments:
            yield from self._compose_segment(seg)

    def _compose_segment(self, seg: Segment) -> ComposeResult:
        if seg.kind == "reasoning":
            yield _ReasoningBlock(seg.text)
            return
        yield Static(seg.text, classes="segment-text", markup=False)
