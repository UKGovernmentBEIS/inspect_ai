"""Message widget — renders one :class:`MessageGroup`.

Two top-level variants by ``role``:

- ``user`` — left-aligned block with ``user · dataset_input`` chip.
- ``assistant`` — left-aligned block with the model chip (drawn from
  ``MessageGroup.model``, falling back to the session-wide current
  model when the group's own attribution is missing).

Text segments render as Markdown (via :class:`rich.markdown.Markdown`)
so fenced code blocks, bold, lists, and inline code come out
formatted instead of showing raw backticks. Reasoning segments render
as dimmed sub-blocks with an expand/collapse toggle (bound to ``^E``
on the focused widget).

Updates happen IN PLACE via :meth:`update_state` — the body Vertical
is always mounted (even if empty initially) and segment widgets are
mounted into it as chunks arrive. Re-rendering existing segments goes
through ``Static.update()`` on the corresponding child widget. This
avoids the visible flash you'd get from tearing the whole bubble down
and rebuilding it on every streaming chunk.
"""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from ..state import MessageGroup, Segment
from .markdown import StyledMarkdown
from .tool_call import _CollapsibleContent

# Braille spinner — same idiom Inspect's task display uses. Ten frames
# is enough to feel like smooth motion without strobing the eye.
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_MESSAGE_TEXT_MAX_LINES = 12
"""Per-text-segment cap before the ``… N more lines`` expander kicks in.

Long agent responses (and the occasional verbose system prompt) can
easily run hundreds of lines; without a cap they push the rest of the
transcript off-screen on every paint. 12 lines fits the typical
operator's "scan the response, decide next action" window — anything
longer reads as documentation and benefits from the click-to-expand
affordance ``_CollapsibleContent`` provides. Reasoning segments use
their own ^E collapse and skip this cap entirely.
"""


def _format_elapsed(seconds: float) -> str:
    """Compact wall-clock formatter for the assistant chip's elapsed timer."""
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


class _ReasoningBlock(Widget, can_focus=True):
    """Collapsible reasoning sub-block within an assistant message.

    Dim by default; ``^E`` toggles expand/collapse. Each block tracks
    its own state so multiple reasoning blocks in one assistant message
    can be expanded independently.
    """

    DEFAULT_CSS = """
    _ReasoningBlock {
        height: auto;
        color: $text-muted;
    }
    _ReasoningBlock .header { text-style: italic; }
    _ReasoningBlock .body {
        padding-left: 2;
        margin-top: 1;
    }
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
        yield Static(StyledMarkdown(self._text), classes="body")
        if self._collapsed:
            self.add_class("collapsed")

    def action_toggle_reasoning(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")
        try:
            header = self.query_one(".header", Static)
            header.update(("▸" if self._collapsed else "▾") + " reasoning")
        except Exception:
            pass

    def on_click(self) -> None:
        # Mirror the ^E keyboard shortcut so a mouse click anywhere in
        # the block toggles expand/collapse — keyboard-only was missing
        # the most natural pointer affordance.
        self.action_toggle_reasoning()

    def set_text(self, text: str) -> None:
        """Replace the reasoning body text in place.

        Lets the parent MessageWidget extend the reasoning content on
        streaming chunks without remounting (and losing the collapsed
        / expanded state the user set).
        """
        self._text = text
        try:
            self.query_one(".body", Static).update(StyledMarkdown(text))
        except Exception:
            pass


class MessageWidget(Widget):
    """Renders one MessageGroup as user or assistant content."""

    DEFAULT_CSS = """
    /* All message bubbles share the same padding + bottom margin so
     * the colored backgrounds form an even rhythm down the
     * transcript. Per-role classes only override the background. Hex
     * values come straight from the message-colors design spec —
     * they're brand tints, not semantic, so Textual theme tokens
     * (``$primary 8%`` etc.) aren't a clean fit. If we ever add
     * theme variants (light mode), swap this palette in one place
     * rather than threading aliases through. */
    MessageWidget {
        height: auto;
        padding: 1 2;
        margin-bottom: 1;
    }
    MessageWidget.system    { background: #262d35; }
    MessageWidget.user      { background: #392113; }
    MessageWidget.user.operator { background: #2f1a2d; }
    MessageWidget.assistant { background: #052740; }
    /* Default chip colour matches body text — markup uses bold for
     * the role word and `[dim]…[/dim]` for the provenance suffix, so
     * the role still reads first against the tinted band. */
    MessageWidget .chip { color: $foreground; }
    /* The body Vertical is always mounted so update_state can append
     * segment widgets without restructuring the parent. ``with-content``
     * class is toggled to enable the top margin only once segments
     * actually exist — otherwise an empty body would add a blank row
     * inside an empty pending bubble. */
    MessageWidget .body { height: auto; }
    MessageWidget .body.with-content { margin-top: 1; }
    MessageWidget .segment-text { height: auto; }
    /* Spacer mounted between adjacent segments — gives reasoning →
     * text (and any future cross-kind transition) a row of air without
     * adding trailing whitespace when reasoning is the only segment. */
    MessageWidget .segment-spacer { height: 1; }
    """

    def __init__(
        self, group: MessageGroup, *, current_model: str | None = None
    ) -> None:
        super().__init__()
        self._group = group
        self._current_model = current_model
        # Spinner frame for the in-flight chip indicator. Only animates
        # while the message has pending=True. The TranscriptWidget's
        # periodic tick calls tick_spinner().
        self._spinner_frame = 0
        # Snapshot of what's currently MOUNTED — distinct from the
        # group's live state because state._consume_chunk mutates
        # segments in place (e.g. appending streaming text to the
        # existing Segment). Comparing self._group to new_group would
        # never show a diff; comparing live values to these snapshots
        # tells us what's actually new since the last paint.
        self._mounted_count = len(group.segments)
        self._mounted_last_text = group.segments[-1].text if group.segments else ""
        self.add_class(group.role)
        # Operator-submitted user messages get a distinct background
        # (plum) so the eye reads them apart from dataset-input user
        # turns. The source is known at widget-creation time because
        # the router emits one full UserMessageChunk per message —
        # the group's ``user_source`` is set on the chunk that creates
        # the group, before _build_widget runs.
        if group.role == "user" and group.user_source == "operator":
            self.add_class("operator")

    def compose(self) -> ComposeResult:
        # ``markup=True`` so we can bold the role word and dim the
        # provenance suffix in one Static.
        yield Static(self._chip_text(), classes="chip", markup=True)
        # Always mount the body container so update_state can append
        # segment widgets without having to restructure the parent.
        # The ``with-content`` class is toggled in on_mount / update.
        body = Vertical(classes="body")
        if self._group.segments:
            body.add_class("with-content")
        with body:
            for i, seg in enumerate(self._group.segments):
                if i > 0:
                    yield Static("", classes="segment-spacer", markup=False)
                yield from self._compose_segment(seg)

    def _chip_text(self) -> str:
        # Role word stands out (bold + default colour); the suffix
        # ("model X" / "input" / "operator") rides as dim provenance
        # so the eye lands on WHO is speaking before the source.
        if self._group.role == "system":
            return "[bold]system[/bold]"
        if self._group.role == "user":
            source = self._group.user_source
            if source:
                return f"[bold]user[/bold] [dim]· {source}[/dim]"
            return "[bold]user[/bold]"
        # Assistant: prefer the group's own model attribution; fall back
        # to the session's current model when the chunk had no
        # `_meta["inspect.model"]` (e.g. an old server).
        model = self._group.model or self._current_model or "—"
        base = f"[bold]assistant[/bold] [dim]· {model}[/dim]"
        # Glyph prefix on every assistant chip — animated braille
        # spinner while the model event is in flight, then a small
        # static bullet once it's complete. Replayed assistant
        # messages come in non-pending so they get the bullet without
        # a spinner phase.
        if self._group.pending:
            glyph = _SPINNER_FRAMES[self._spinner_frame % len(_SPINNER_FRAMES)]
        else:
            glyph = "•"
        # Retry counter + elapsed timer ride as dot-separated dim
        # provenance segments — same separator as "assistant · model"
        # so the eye reads the whole chip as a uniform "key · key · key"
        # row rather than "label model suffix-glob".
        extras: list[str] = []
        if self._group.retries > 0:
            extras.append(f"(retry {self._group.retries})")
        if self._group.pending_started_at is not None and (
            self._group.pending or self._group.retries > 0
        ):
            elapsed = time.monotonic() - self._group.pending_started_at
            extras.append(_format_elapsed(elapsed))
        suffix = "".join(f" [dim]· {e}[/dim]" for e in extras)
        return f"[dim]{glyph}[/dim] {base}{suffix}"

    def tick_spinner(self) -> None:
        """Advance the spinner / elapsed timer and re-render the chip.

        Called from the SessionScreen's periodic tick. Re-renders
        whenever the chip carries live data — either the pending
        spinner or the ticking elapsed timer.
        """
        if not self._group.pending:
            return
        self._spinner_frame += 1
        self._refresh_chip()

    def _refresh_chip(self) -> None:
        try:
            self.query_one(".chip", Static).update(self._chip_text())
        except Exception:
            pass

    def update_state(self, new_group: MessageGroup) -> None:
        """Re-bind to a (possibly mutated) group and update in place.

        Streaming text chunks extend the last segment widget rather
        than remounting the whole bubble — preserves the
        ``_ReasoningBlock`` collapsed/expanded state, keeps the
        scrollback steady, and eliminates the visible flash that
        full-remount produced on every chunk.

        Three update cases, compared against the widget-local
        snapshots (``_mounted_count`` / ``_mounted_last_text``)
        because the group object itself mutates in place:

        - **Same segment count, last grew**: update the last segment
          widget's content via ``Static.update`` / ``set_text``.
        - **New segments appended**: mount the new ones (plus spacers)
          on the body Vertical.
        - **Chip-only changes** (pending flip, retries++, model name):
          re-render the chip Static.
        """
        self._group = new_group
        # Chip always re-renders — it carries the pending / retry /
        # model state, any of which can have flipped.
        self._refresh_chip()

        new_segs = new_group.segments
        new_count = len(new_segs)
        new_last_text = new_segs[-1].text if new_segs else ""

        if new_count > self._mounted_count:
            # New segments arrived. Any in-place extension of the
            # previously-last segment lands first (multiple chunks can
            # batch between notifications); then the new segments
            # mount.
            if self._mounted_count > 0:
                prev_last_idx = self._mounted_count - 1
                if new_segs[prev_last_idx].text != self._mounted_last_text:
                    self._update_last_segment_widget(new_segs[prev_last_idx])
            self._mount_new_segments(self._mounted_count)
            self._mounted_count = new_count
            self._mounted_last_text = new_last_text
        elif new_count == self._mounted_count and new_count > 0:
            # Last segment may have been extended by a streaming chunk.
            if new_last_text != self._mounted_last_text:
                self._update_last_segment_widget(new_segs[-1])
                self._mounted_last_text = new_last_text
        # new_count < self._mounted_count would mean segments were
        # removed — state never does that, so no branch.

    def _body(self) -> Vertical | None:
        try:
            return self.query_one(".body", Vertical)
        except Exception:
            return None

    def _update_last_segment_widget(self, seg: Segment) -> None:
        """Replace the last segment widget's content with the new text."""
        body = self._body()
        if body is None:
            return
        # Walk backward to find the last NON-spacer child — that's the
        # widget rendering the last segment.
        last_widget: Widget | None = None
        for child in reversed(list(body.children)):
            if isinstance(child, Static) and child.has_class("segment-spacer"):
                continue
            last_widget = child
            break
        if last_widget is None:
            return
        if seg.kind == "text" and isinstance(last_widget, _CollapsibleContent):
            # Streaming chunks land here — replace_text re-runs the
            # truncate-or-expand decision in place so a growing
            # response gains its "… N more lines" affordance the
            # moment it crosses the cap.
            last_widget.replace_text(seg.text)
        elif seg.kind == "reasoning" and isinstance(last_widget, _ReasoningBlock):
            last_widget.set_text(seg.text)

    def _mount_new_segments(self, start: int) -> None:
        """Mount segment widgets (+ spacers) for ``segments[start:]``.

        Toggles the body's ``with-content`` class on the first
        mounted segment so the top margin gets activated only when
        there's actual content (not for empty pending bubbles).
        """
        body = self._body()
        if body is None:
            return
        if not body.has_class("with-content"):
            body.add_class("with-content")
        for i in range(start, len(self._group.segments)):
            seg = self._group.segments[i]
            if i > 0:
                body.mount(Static("", classes="segment-spacer", markup=False))
            if seg.kind == "reasoning":
                body.mount(_ReasoningBlock(seg.text))
            else:
                body.mount(
                    _CollapsibleContent(seg.text, max_lines=_MESSAGE_TEXT_MAX_LINES)
                )

    def _compose_segment(self, seg: Segment) -> ComposeResult:
        if seg.kind == "reasoning":
            yield _ReasoningBlock(seg.text)
            return
        # Text via _CollapsibleContent so long responses get the
        # ``… N more lines`` expander instead of pushing the
        # transcript off-screen. Markdown rendering happens inside —
        # fenced code blocks, bold, lists, inline code all still
        # render formatted.
        yield _CollapsibleContent(seg.text, max_lines=_MESSAGE_TEXT_MAX_LINES)
