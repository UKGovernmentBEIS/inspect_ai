"""Truncated-text widget shared by :class:`ToolCallWidget` and :class:`MessageWidget`.

Renders ``max_lines`` of text plus, when the source was longer, a
clickable underlined ``… N more lines`` indicator. Clicking expands
the body in place and removes the note — one-way (no collapse back;
once you've asked to see the rest you want to keep seeing it).

Lives here, not in :mod:`tool_call`, because both the tool-call body
and assistant message bodies mount it; keeping it co-located with one
caller forced a backwards import that obscured the dependency graph.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from inspect_ai._util.rich import clean_control_characters
from inspect_ai._util.text import truncate_lines

from ._scroll import schedule_scroll_to_end_if_at_bottom
from .markdown import StyledMarkdown


class CollapsibleContent(Widget):
    """Truncated body text that expands when the more-lines note is clicked.

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
    CollapsibleContent { height: auto; }
    CollapsibleContent .body-content { height: auto; }
    /* Truncation note styling lives on the widget itself (not on the
     * parent) so the affordance reads consistently whether
     * CollapsibleContent is mounted inside a tool card or a message
     * bubble. Underlined + muted telegraphs "click to expand"; hover
     * tint mirrors the usual TUI clickable convention. */
    CollapsibleContent .truncation-note {
        color: $text-muted;
        text-style: italic underline;
        height: auto;
    }
    CollapsibleContent .truncation-note:hover { color: $accent; }
    """

    def __init__(self, full_text: str, *, max_lines: int) -> None:
        super().__init__()
        self._full_text = clean_control_characters(full_text)
        self._max_lines = max_lines
        self._expanded = False

    def compose(self) -> ComposeResult:
        shown, omitted = truncate_lines(self._full_text, max_lines=self._max_lines)
        yield Static(StyledMarkdown(shown), classes="body-content", id="cc-body")
        if omitted is not None and omitted > 0:
            yield Static(
                _more_lines_label(omitted),
                classes="truncation-note",
                id="cc-note",
                markup=False,
            )

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
        except NoMatches:
            return
        try:
            self.query_one("#cc-note", Static).remove()
        except NoMatches:
            pass
        # Auto-scroll to keep the newly-expanded content visible if the
        # operator was at the bottom of the transcript before clicking.
        schedule_scroll_to_end_if_at_bottom(self)

    def replace_text(self, text: str) -> None:
        """Replace the underlying text in place — for streaming tail growth.

        ToolCallWidget calls this when a ToolCallProgress extends the
        last content item rather than appending a new one. Updating
        the body text + truncation note avoids a full re-mount that
        would flash the surrounding card.
        """
        self._full_text = clean_control_characters(text)
        try:
            body_static = self.query_one("#cc-body", Static)
        except NoMatches:
            return
        if self._expanded:
            body_static.update(StyledMarkdown(self._full_text))
            return
        shown, omitted = truncate_lines(self._full_text, max_lines=self._max_lines)
        body_static.update(StyledMarkdown(shown))
        # Note may or may not exist yet — recreate it conditionally so
        # late-arriving truncation (text grew past the limit) gets a
        # clickable expander.
        try:
            existing_note: Static | None = self.query_one("#cc-note", Static)
        except NoMatches:
            existing_note = None
        if omitted is not None and omitted > 0:
            label = _more_lines_label(omitted)
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


def _more_lines_label(omitted: int) -> str:
    return f"… {omitted} more line{'s' if omitted != 1 else ''}"
