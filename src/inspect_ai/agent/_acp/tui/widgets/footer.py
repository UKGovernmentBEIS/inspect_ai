"""Footer subclass that flushes the terminal-action cluster to the right.

Textual's :class:`~textual.widgets.Footer` renders bindings packed
left-to-right in the order returned by :attr:`Screen.active_bindings`,
which leaves no visual separation between the everyday command keys
(submit / interrupt / plan / …) and the navigation-or-terminal keys
(cancel sample / switch sample / quit). This subclass:

1. Picks out the right-cluster actions (cancel_sample, switch_sample,
   quit) in a fixed order so the cluster reads
   ``cancel | switch | quit`` regardless of binding-discovery order.
2. Inserts a flexible-width spacer between the left and right groups
   so the right cluster sits flush against the screen edge, giving
   the eye a clear "navigate / end this" zone separate from the
   day-to-day action keys.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, Static

# Actions pinned to the right cluster, in the order they should appear
# from left to right. Items missing from the current screen's bindings
# (e.g. ``cancel_sample`` once the lifecycle is ``complete``) are
# simply skipped — the cluster compresses without leaving a gap.
_RIGHT_CLUSTER_ACTIONS: tuple[str, ...] = ("cancel_sample", "switch_sample", "quit")


class _FooterSpacer(Static):
    """Flexible-width filler between left and right footer groups."""

    DEFAULT_CSS = """
    _FooterSpacer {
        width: 1fr;
        height: 1;
        background: transparent;
    }
    """

    def __init__(self) -> None:
        # Empty content; the widget exists only for its layout
        # contribution.
        super().__init__("", markup=False)


class AppFooter(Footer):
    """Footer with a right-flushed cluster of nav/terminal actions."""

    def compose(self) -> ComposeResult:
        left: list[object] = []
        right_by_action: dict[str, object] = {}
        for widget in super().compose():
            # Standalone ``FooterKey`` widgets expose an ``action``
            # attribute; group/label widgets don't. Duck-type check
            # avoids importing from textual.widgets._footer (private
            # module).
            action = getattr(widget, "action", None)
            if action in _RIGHT_CLUSTER_ACTIONS:
                # Last-wins on duplicates (the base App inherits a
                # default ``ctrl+q`` quit binding alongside our
                # explicit ``ctrl+x`` quit; both have action="quit").
                # Keeping the most recently discovered one matches the
                # earlier single-quit-widget behaviour.
                right_by_action[action] = widget
            else:
                left.append(widget)
        yield from left  # type: ignore[misc]
        # Only insert the spacer when at least one right-cluster
        # binding is actually present; otherwise the footer would
        # show an empty trailing region.
        if right_by_action:
            yield _FooterSpacer()
            for action in _RIGHT_CLUSTER_ACTIONS:
                right_widget = right_by_action.get(action)
                if right_widget is not None:
                    yield right_widget  # type: ignore[misc]
