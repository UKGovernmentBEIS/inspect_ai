"""Shared helper for "expand-link" widgets to keep auto-scroll in sync.

Four click-to-expand widgets — :class:`_ReasoningBlock` (assistant
message body), :class:`_TracebackBlock` (error event chip),
:class:`_ExplanationBlock` (score chip), and :class:`CollapsibleContent`
(tool-call body + score answer) — all change their mounted height
when the operator clicks them open. If the operator was already at
the bottom of the transcript before clicking, the new content extends
past the viewport with no auto-scroll, leaving them looking at the
old "above the fold" frame even though the just-expanded content is
exactly what they wanted to see.

The fix is one shared helper called from every on_click: walk up the
DOM looking for the transcript ancestor and ask it to schedule its
normal "scroll to bottom" path (which already handles user-pullaway
protection). Duck-typed (``hasattr``) rather than isinstance so this
module stays import-free of :mod:`transcript` and we don't create a
circular import.
"""

from __future__ import annotations

from textual.widget import Widget


def schedule_scroll_to_end_if_at_bottom(widget: Widget) -> None:
    """Auto-scroll the containing transcript when click-expanding near the bottom.

    Captures the at-bottom state BEFORE the caller's toggle has been
    applied isn't necessary here — Textual's ``on_click`` dispatch is
    synchronous and the toggle has typically just happened; the
    transcript's ``_is_at_bottom`` uses a generous tolerance window
    (``_AT_BOTTOM_TOLERANCE``) that survives the brief layout
    invalidation. Callers should invoke this immediately after their
    ``toggle_class`` / ``add_class`` call.
    """
    for ancestor in widget.ancestors:
        scheduler = getattr(ancestor, "_schedule_scroll_to_end", None)
        is_at_bottom = getattr(ancestor, "_is_at_bottom", None)
        if scheduler is None or is_at_bottom is None:
            continue
        if is_at_bottom():
            scheduler()
        return
