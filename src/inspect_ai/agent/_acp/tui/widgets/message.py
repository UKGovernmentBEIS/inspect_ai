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
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from ..state import MessageGroup, Segment
from ._collapsible import CollapsibleContent
from ._formatting import SPINNER_FRAMES, format_duration
from .markdown import StyledMarkdown

_MESSAGE_TEXT_MAX_LINES = 12
"""Per-text-segment cap before the ``… N more lines`` expander kicks in.

Long agent responses (and the occasional verbose system prompt) can
easily run hundreds of lines; without a cap they push the rest of the
transcript off-screen on every paint. 12 lines fits the typical
operator's "scan the response, decide next action" window — anything
longer reads as documentation and benefits from the click-to-expand
affordance ``CollapsibleContent`` provides.
"""


# Per-role chip colour. Role identification comes from the coloured
# bullet + role word plus the body's left-indent under the role word
# — backgrounds were redundant once that landed and were removed to
# quiet the transcript. Hex values are brand tints, not theme tokens;
# if a light theme arrives this dict is the lift-and-shift point.
_PALETTE: dict[str, str] = {
    "system": "#7aa2f7",
    "user": "#e0af68",
    "operator": "#bb9af7",
    "assistant": "#7aa2f7",
}


class _ReasoningBlock(Widget):
    """Click-to-toggle reasoning block.

    Default state shows ONLY the word "reasoning" rendered with the
    same italic + underline + muted treatment :class:`CollapsibleContent`
    uses for its "…N more lines" affordance — so the operator reads
    the link as clickable on sight without a fresh visual vocabulary
    to learn. Click anywhere on the block to expand the body in
    place; click again to collapse it back to the resting link.

    Reasoning is signal-heavy when needed but visually noisy by
    default; this keeps the resting transcript clean and lets the
    operator opt in to detail — and back out of it when they're done.
    """

    DEFAULT_CSS = """
    /* Default to a 1-row bottom margin so an expanded reasoning body
     * doesn't run flush into the assistant text that follows. The two
     * overrides below zero it back out in the cases where the margin
     * would be wasted space:
     *   - ``.collapsed``: only the link is visible, nothing below to
     *     separate from.
     *   - ``:last-child``: nothing follows in the message body, so
     *     the margin would just add a blank row before the message's
     *     own bottom margin. */
    _ReasoningBlock { height: auto; margin-bottom: 1; }
    _ReasoningBlock.collapsed { margin-bottom: 0; }
    _ReasoningBlock:last-child { margin-bottom: 0; }
    /* Link styling mirrors CollapsibleContent's .truncation-note so
     * the affordance reads consistently across the transcript:
     * italic + underline + muted, with an accent hover tint. */
    _ReasoningBlock .reasoning-link {
        color: $text-muted;
        text-style: italic underline;
        height: auto;
    }
    _ReasoningBlock .reasoning-link:hover { color: $accent; }
    _ReasoningBlock .reasoning-body {
        color: $text-muted;
        height: auto;
    }
    /* Body hidden until the click expands. Toggled by removing the
     * ``collapsed`` class in ``on_click``. */
    _ReasoningBlock.collapsed .reasoning-body { display: none; }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        # Start collapsed — only the "reasoning" link is visible.
        self.add_class("collapsed")

    def compose(self) -> ComposeResult:
        yield Static("reasoning", classes="reasoning-link")
        yield Static(StyledMarkdown(self._text), classes="reasoning-body")

    def on_click(self) -> None:
        # Toggle — click expands when collapsed, collapses when
        # expanded. Diverges from CollapsibleContent (which is
        # one-way) because reasoning bodies are typically scannable
        # rather than something you copy out, so making the operator
        # rescroll to hide them again would be friction.
        self.toggle_class("collapsed")

    def set_text(self, text: str) -> None:
        """Replace the reasoning body text in place.

        Lets the parent MessageWidget extend the reasoning content on
        streaming chunks without remounting (and without losing the
        expanded state if the operator already clicked).
        """
        self._text = text
        try:
            self.query_one(".reasoning-body", Static).update(StyledMarkdown(self._text))
        except NoMatches:
            pass


class MessageWidget(Widget):
    """Renders one MessageGroup as user or assistant content."""

    # No background tints — role identification rides entirely on the
    # coloured bullet + role word (from ``_PALETTE``) and the body's
    # ``padding-left: 2`` indent under the role word. The ``operator``
    # CSS class is still added so future styling can hook off it
    # without restructuring widget composition.
    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        padding: 0 2;
        margin-bottom: 1;
    }
    MessageWidget .chip { color: $foreground; }
    MessageWidget .body {
        height: auto;
        padding-left: 2;
    }
    MessageWidget .segment-text { height: auto; }
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
        # ``markup=True`` so we can colour the bullet + role word and
        # dim the provenance suffix in one Static.
        yield Static(self._chip_text(), classes="chip", markup=True)
        # Always mount the body container so update_state can append
        # segment widgets without having to restructure the parent.
        # Segments now sit flush — no inter-segment spacer widgets.
        with Vertical(classes="body"):
            for seg in self._group.segments:
                yield from self._compose_segment(seg)

    def _chip_text(self) -> str:
        # Bullet + role word both carry the role colour from _PALETTE
        # so each speaker is identifiable without relying on the
        # background tint. Provenance suffix ("· input" / "· operator"
        # / "· model-name") stays dim so the role word reads first
        # against the band.
        fg = _PALETTE[self._palette_key()]
        if self._group.role == "system":
            return f"[{fg}]•[/] [bold {fg}]system[/]"
        if self._group.role == "user":
            source = self._group.user_source
            base = f"[bold {fg}]user[/]"
            if source:
                base = f"{base} [dim]· {source}[/dim]"
            return f"[{fg}]•[/] {base}"
        # Assistant: prefer the group's own model attribution; fall back
        # to the session's current model when the chunk had no
        # `_meta["inspect.model"]` (e.g. an old server).
        model = self._group.model or self._current_model or "—"
        base = f"[bold {fg}]assistant[/] [dim]· {model}[/dim]"
        # Glyph prefix on every assistant chip — animated braille
        # spinner while the model event is in flight, then a small
        # static bullet once it's complete. Both pick up the role
        # colour so the spinner reads as "this speaker is in flight".
        if self._group.pending:
            glyph = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
        else:
            glyph = "•"
        # Live progress indicators — elapsed timer + retry counter +
        # "esc to interrupt" hint — only render while ``pending``.
        # Once the generation has completed (or been interrupted) the
        # operator no longer needs the live signals, and the elapsed
        # timer would otherwise keep growing on every subsequent
        # re-render (``pending_started_at`` never resets).
        suffix = ""
        if self._group.pending:
            if self._group.pending_started_at is not None:
                elapsed = format_duration(
                    time.monotonic() - self._group.pending_started_at
                )
                suffix += f" [dim]· {elapsed}[/dim]"
            # Retry counter rides as a parens-note. The
            # "esc to interrupt" affordance lives in the composer
            # placeholder while ``lifecycle == "running"`` (single
            # source of truth) — repeating it on every chip was noise.
            if self._group.retries > 0:
                suffix += f" [dim](retry {self._group.retries})[/dim]"
        return f"[{fg}]{glyph}[/] {base}{suffix}"

    def _palette_key(self) -> str:
        """Resolve the MessageGroup role + source to a ``_PALETTE`` key.

        The dict has four keys (system / user / operator / assistant)
        and the operator user is a sub-case of user — so this small
        helper centralises the mapping rather than threading the
        if/elif chain through every call site.
        """
        if self._group.role == "user" and self._group.user_source == "operator":
            return "operator"
        if self._group.role == "user":
            return "user"
        if self._group.role == "system":
            return "system"
        return "assistant"

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
        except NoMatches:
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
        except NoMatches:
            return None

    def _update_last_segment_widget(self, seg: Segment) -> None:
        """Replace the last segment widget's content with the new text."""
        body = self._body()
        if body is None:
            return
        children = list(body.children)
        if not children:
            return
        last_widget = children[-1]
        if seg.kind == "text" and isinstance(last_widget, CollapsibleContent):
            # Streaming chunks land here — replace_text re-runs the
            # truncate-or-expand decision in place so a growing
            # response gains its "… N more lines" affordance the
            # moment it crosses the cap.
            last_widget.replace_text(seg.text)
        elif seg.kind == "reasoning" and isinstance(last_widget, _ReasoningBlock):
            last_widget.set_text(seg.text)

    def _mount_new_segments(self, start: int) -> None:
        """Mount segment widgets for ``segments[start:]`` — no spacers."""
        body = self._body()
        if body is None:
            return
        for i in range(start, len(self._group.segments)):
            seg = self._group.segments[i]
            if seg.kind == "reasoning":
                body.mount(_ReasoningBlock(seg.text))
            else:
                body.mount(
                    CollapsibleContent(seg.text, max_lines=_MESSAGE_TEXT_MAX_LINES)
                )

    def _compose_segment(self, seg: Segment) -> ComposeResult:
        if seg.kind == "reasoning":
            yield _ReasoningBlock(seg.text)
            return
        # Text via CollapsibleContent so long responses get the
        # ``… N more lines`` expander instead of pushing the
        # transcript off-screen. Markdown rendering happens inside —
        # fenced code blocks, bold, lists, inline code all still
        # render formatted.
        yield CollapsibleContent(seg.text, max_lines=_MESSAGE_TEXT_MAX_LINES)
