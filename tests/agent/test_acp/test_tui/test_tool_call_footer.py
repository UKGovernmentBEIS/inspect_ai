"""Fast pure-function tests for ``ToolCallWidget._header_text`` composition.

The header now carries the status glyph, duration, approval decision,
and ``cancelling…`` marker (all on one line) — these used to live in a
separate footer row that's since been removed. Testing the function
directly avoids paying the Textual app-bootstrap cost on every
composition assertion.

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
    it just snapshots header / item signatures for later diffing.
    Safe to instantiate directly for pure-function tests.
    """
    return ToolCallWidget(state)


# ---------------------------------------------------------------------------
# In-flight header is bullet glyph + name + duration (no inline affordance)
# ---------------------------------------------------------------------------


def test_in_flight_header_is_bullet_name_and_duration() -> None:
    """In-flight cards show no per-card cancel affordance.

    The cancel surface is the screen-level ``^L cancel tool`` footer
    hint — duplicating it per-card was discarded in favour of a
    quieter visual register on each tool row.
    """
    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    widget = _widget(tc)

    header = widget._header_text()  # noqa: SLF001 — test access

    assert "cancel tool call" not in header
    assert "^l" not in header
    assert "cancelling" not in header
    # Sanity: still carries the duration suffix (dim · Ns format).
    assert "· 0" in header  # the dot-separator + elapsed timer


# ---------------------------------------------------------------------------
# cancel_requested → "cancelling…" feedback
# ---------------------------------------------------------------------------


def test_header_shows_cancelling_marker_after_request() -> None:
    """``cancel_requested=True`` adds a dim ``cancelling…`` suffix.

    Only visual feedback that the operator's ``^L`` registered; the
    card transitions to terminal (``✗``) within ~1s as the server's
    synthesized failure status lands.
    """
    tc = ToolCallState(tool_call_id="tc-1", title="bash", status="in_progress")
    tc.cancel_requested = True
    widget = _widget(tc)

    header = widget._header_text()  # noqa: SLF001

    assert "cancelling" in header


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

    header = widget._header_text()  # noqa: SLF001

    assert "cancelling" not in header
    assert "✗" in header


# ---------------------------------------------------------------------------
# Pending-approval gating
# ---------------------------------------------------------------------------


def test_pending_approval_header_short_circuits() -> None:
    """Pending approval suffixes ``· approval requested`` and drops the timer."""
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

    header = widget._header_text()  # noqa: SLF001

    # Header still shows the tool name + spinner, plus a static
    # "approval requested" suffix instead of the elapsed timer (the
    # timer would just be measuring operator think-time).
    assert "approval requested" in header
    assert "bash" in header
    # No elapsed timer while pending approval — the dot-separated
    # ``· Ns`` suffix is suppressed.
    assert "· 0" not in header


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

    header = widget._header_text()  # noqa: SLF001

    assert "approved by you" in header
    # Completed tool calls render the gear glyph; ``✓`` is reserved
    # for score chips and other "verdict" surfaces.
    assert "⚙" in header
