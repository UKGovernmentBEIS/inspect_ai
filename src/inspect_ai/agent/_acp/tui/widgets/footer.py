"""Footer subclass that pins the app-level ``quit`` key to the right.

Textual's :class:`~textual.widgets.Footer` renders bindings in the
order returned by :attr:`Screen.active_bindings`, which interleaves
app-level and screen-level bindings by discovery order. That leaves
``quit`` somewhere in the middle of the action group on our screens
rather than at the rightmost position where keyboard-shortcut rows
conventionally place destructive keys. This subclass simply
reorders compose output so any binding whose action is ``quit``
ends up last.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer


class AppFooter(Footer):
    """Footer that yields the ``quit`` FooterKey after all other keys."""

    def compose(self) -> ComposeResult:
        rest = []
        quit_widget = None
        for widget in super().compose():
            # Standalone ``FooterKey`` widgets expose an ``action``
            # attribute; group/label widgets don't. Duck-type check
            # avoids importing from textual.widgets._footer (private
            # module).
            if getattr(widget, "action", None) == "quit":
                quit_widget = widget
            else:
                rest.append(widget)
        yield from rest
        if quit_widget is not None:
            yield quit_widget
