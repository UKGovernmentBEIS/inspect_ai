"""Hashable fingerprints for tool-call content items + states.

Used by :mod:`transcript` to decide when an in-flight tool card's
visible content has actually changed (so the auto-scroll heuristic
follows live-tail) and by :mod:`tool_call` to gate its body diff /
patch logic against the mounted snapshot.

Module-level so the transcript layer can compute a fingerprint without
instantiating a widget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..state import ToolCallState


def item_signature(item: object) -> tuple[Any, ...]:
    """Hashable fingerprint of a single tool-call content item.

    Same shape regardless of caller — the transcript uses it for
    scroll-tracking, the tool-call widget uses it to diff against
    the mounted body.
    """
    type_name = getattr(item, "type", None)
    if type_name == "content":
        inner = getattr(item, "content", None)
        text = getattr(inner, "text", "") if inner is not None else ""
        return ("content", len(text or ""), hash(text or ""))
    if type_name == "diff":
        old_text = getattr(item, "old_text", "") or ""
        new_text = getattr(item, "new_text", "") or ""
        return (
            "diff",
            getattr(item, "path", ""),
            hash(old_text),
            hash(new_text),
        )
    if type_name == "terminal":
        return ("terminal", getattr(item, "terminal_id", ""))
    return (type_name or "unknown",)


def tool_state_fingerprint(state: "ToolCallState") -> tuple[Any, ...]:
    """Comprehensive change signature for a ToolCallState.

    Returns a hashable tuple that changes whenever anything the user
    would see changes: status, title, kind, the list of content items
    (with text hashes so same-length replacements register), the
    raw_input shape (plan-style tools render from raw_input not
    content), the approval slot (pending / resolved-decision),
    AND the ``cancel_requested`` flag (drives the footer's
    ``cancelling…`` marker). Any user-visible field MUST be in this
    tuple or the transcript's mounted-snapshot diff skips
    ``update_state`` and the card never re-renders on the
    state-notification — at best the 0.5s tick re-renders it,
    losing the immediate-feedback contract the state mutations
    promise. The transcript layer also uses this to gate the
    auto-scroll decision so live-tail follows in-progress tool
    output.
    """
    content_sig = tuple(item_signature(item) for item in (state.content or []))
    # raw_input shape matters for plan-style tools which render their
    # body from it. Use repr — it's stable for the dict shapes Inspect
    # produces and avoids importing the plan-extraction logic here.
    raw_input_sig: object
    if isinstance(state.raw_input, dict):
        raw_input_sig = hash(repr(sorted(state.raw_input.items(), key=str)))
    else:
        raw_input_sig = repr(state.raw_input)
    # Approval slot fingerprint — boolean for "is there a pending
    # request" (we don't hash the request payload itself; the
    # section reads it directly off the PendingApproval ref, and
    # we don't expect the same tool_call_id to receive a second,
    # different request) + the resolved decision label.
    approval_sig = (
        state.pending_approval is not None,
        state.last_approval_decision or "",
    )
    return (
        state.status,
        state.title or "",
        state.kind or "",
        content_sig,
        raw_input_sig,
        approval_sig,
        state.cancel_requested,
    )
