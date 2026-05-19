"""Fast pure-function tests for ``ToolCallWidget._footer_text`` composition.

The footer string is composed deterministically from the bound
``ToolCallState``. Both the spinner-tick path and the post-mutation
re-render path call ``_footer_text()`` to derive the new
Rich-markup string; testing the function directly avoids paying the
Textual app-bootstrap cost on every footer-composition assertion.

The cancel-tool-call affordance itself lives in the screen footer
(``^L cancel tool`` keybind), NOT on individual cards — the only
cancel-related visual on a card is the dim ``cancelling…`` marker
that appears after the operator hits ``^L``, as feedback while the
synthesized failure status propagates.
"""

from __future__ import annotations

from inspect_ai.agent._acp.tui.state import ToolCallState
from inspect_ai.agent._acp.tui.widgets.tool_call import ToolCallWidget


def _widget(state: ToolCallState) -> ToolCallWidget:
    """Construct a ToolCallWidget without mounting it.

    ``ToolCallWidget.__init__`` doesn't touch any Textual app state —
    it just snapshots header / footer / item signatures for later
    diffing. Safe to instantiate directly for pure-function tests.
    """
    return ToolCallWidget(state)


# ---------------------------------------------------------------------------
# In-flight footer is bare glyph + duration (no inline affordance)
# ---------------------------------------------------------------------------


def test_in_flight_footer_is_just_glyph_and_duration() -> None:
    """In-flight cards show no per-card cancel affordance.

    The cancel surface is the screen-level ``^L cancel tool`` footer
    hint — duplicating it per-card was discarded in favour of a
    quieter visual register on each tool row.
    """
    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    widget = _widget(tc)

    footer = widget._footer_text()  # noqa: SLF001 — test access

    assert "cancel tool call" not in footer
    assert "^l" not in footer
    assert "cancelling" not in footer
    # Sanity: still carries SOMETHING — the spinner glyph.
    assert footer  # non-empty


# ---------------------------------------------------------------------------
# cancel_requested → "cancelling…" feedback
# ---------------------------------------------------------------------------


def test_footer_shows_cancelling_marker_after_request() -> None:
    """``cancel_requested=True`` adds a dim ``cancelling…`` suffix.

    Only visual feedback that the operator's ``^L`` registered; the
    card transitions to terminal (``✗``) within ~1s as the server's
    synthesized failure status lands.
    """
    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    tc.cancel_requested = True
    widget = _widget(tc)

    footer = widget._footer_text()  # noqa: SLF001

    assert "cancelling" in footer


def test_terminal_card_omits_cancelling_marker() -> None:
    """Once the card transitions terminal, drop the ``cancelling…`` marker.

    The terminal glyph (``✓`` / ``✗``) IS the final state — no need
    to layer the transient marker on top of it.
    """
    tc = ToolCallState(
        tool_call_id="tc-1", title="bash", status="failed", end_time=10.0
    )
    tc.start_time = 5.0
    tc.cancel_requested = True  # was true mid-flight; now terminal
    widget = _widget(tc)

    footer = widget._footer_text()  # noqa: SLF001

    assert "cancelling" not in footer
    assert "✗" in footer


# ---------------------------------------------------------------------------
# Pending-approval gating
# ---------------------------------------------------------------------------


def test_pending_approval_footer_short_circuits() -> None:
    """Pending approval renders the dedicated placeholder, no other footer text."""
    import asyncio

    from acp.schema import (
        PermissionOption,
        RequestPermissionRequest,
        ToolCallUpdate,
    )

    from inspect_ai.agent._acp.tui.state import PendingApproval

    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="pending")
    request = RequestPermissionRequest(
        session_id="sid",
        tool_call=ToolCallUpdate(tool_call_id="tc-1", title="bash", status="pending"),
        options=[
            PermissionOption(option_id="approve", name="Approve", kind="allow_once")
        ],
    )
    tc.pending_approval = PendingApproval(request=request, event=asyncio.Event())
    widget = _widget(tc)

    footer = widget._footer_text()  # noqa: SLF001

    assert footer == "tool call approval requested"


# ---------------------------------------------------------------------------
# Approval-decision suffix still works alongside cancel_requested
# ---------------------------------------------------------------------------


def test_completed_card_with_approval_decision_keeps_suffix() -> None:
    """Terminal status + a resolved approval renders the colour-coded decision."""
    tc = ToolCallState(
        tool_call_id="tc-1", title="bash", status="completed", end_time=10.0
    )
    tc.start_time = 5.0
    tc.last_approval_decision = "approved"
    widget = _widget(tc)

    footer = widget._footer_text()  # noqa: SLF001

    assert "approved by you" in footer
    assert "✓" in footer
