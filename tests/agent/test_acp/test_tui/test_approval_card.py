"""Textual harness tests for the inline approval card.

Mirrors ``test_elicitation_card.py``: mounts the card in a minimal
:class:`App`, drives button clicks through the real event loop, and
asserts the typed :class:`ApprovalDecisionRequested` bubble carries
the expected ``tool_call_id`` + ``option_id``.
"""

from __future__ import annotations

import asyncio

import pytest
from acp.schema import (
    PermissionOption,
    RequestPermissionRequest,
    ToolCallUpdate,
)
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Button

from inspect_ai.agent._acp.tui.state import PendingApproval
from inspect_ai.agent._acp.tui.widgets.approval_card import _ApprovalCard
from inspect_ai.agent._acp.tui.widgets.tool_call import (
    _BUTTON_ID_PREFIX,
    ApprovalDecisionRequested,
)


def _pending(
    tool_call_id: str = "tc1",
    function: str = "bash",
    arguments: dict[str, object] | None = None,
    options: list[PermissionOption] | None = None,
    title: str | None = None,
) -> PendingApproval:
    if arguments is None:
        arguments = {"command": "ls -la"}
    if options is None:
        options = [
            PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
        ]
    # ``title`` mirrors what the wire layer (the human-approver shim
    # in ``approval/_human/acp.py``) writes: it's already the
    # ``descriptive_title(function, arguments)`` output, not the bare
    # function name. Tests that care about the descriptive form
    # should pass ``title=`` explicitly to avoid drift from the
    # production helper.
    if title is None:
        title = function
    return PendingApproval(
        request=RequestPermissionRequest(
            session_id="sess-1",
            tool_call=ToolCallUpdate(
                tool_call_id=tool_call_id,
                title=title,
                raw_input=arguments,
                status="pending",
            ),
            options=options,
        ),
        event=asyncio.Event(),
    )


class _CardApp(App[None]):
    """Minimal host capturing :class:`ApprovalDecisionRequested` bubbles."""

    def __init__(self, pending: PendingApproval) -> None:
        super().__init__()
        self._pending = pending
        self.bubbles: list[ApprovalDecisionRequested] = []

    def compose(self) -> ComposeResult:
        yield _ApprovalCard(self._pending)

    def on_approval_decision_requested(
        self, message: ApprovalDecisionRequested
    ) -> None:
        self.bubbles.append(message)
        message.stop()


# ---------------------------------------------------------------------------
# from_pending + identity slot
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_from_pending_pins_identity() -> None:
    """``.request`` is the PendingApproval identity for stale-replace."""
    pending = _pending()
    card = _ApprovalCard.from_pending(pending)
    assert card.request is pending


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_card_renders_descriptive_title_in_header() -> None:
    """Header reads ``"Tool Approval"`` + dim title verbatim from ``call.title``.

    The wire layer (``approval/_human/acp.py:_build_request``)
    already runs :func:`descriptive_title` and writes the result
    into ``ToolCallUpdate.title``. The card renders that string
    verbatim — re-running ``descriptive_title`` here would
    double-append the argument summary (regression: the old code
    produced ``"dangerous_action rm -rf … rm -rf …"``). We assert
    the descriptive title appears exactly once.
    """
    from textual.widgets import Static

    pending = _pending(
        function="bash",
        arguments={"command": "ls -la"},
        title="bash ls -la",
    )
    async with _CardApp(pending).run_test() as pilot:
        header = pilot.app.query_one(".request-header", Static)
        rendered = str(header.render())
        assert "Tool Approval" in rendered
        assert rendered.count("bash ls -la") == 1


@skip_if_trio
@pytest.mark.anyio
async def test_card_renders_one_compact_button_per_option() -> None:
    """Each PermissionOption mounts as a compact Button with the id prefix."""
    pending = _pending(
        options=[
            PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
            PermissionOption(option_id="modify", name="Modify", kind="allow_once"),
        ]
    )
    async with _CardApp(pending).run_test() as pilot:
        actions = pilot.app.query_one("#request-actions")
        buttons = list(actions.query(Button))
        assert [b.id for b in buttons] == [
            f"{_BUTTON_ID_PREFIX}approve",
            f"{_BUTTON_ID_PREFIX}reject",
            f"{_BUTTON_ID_PREFIX}modify",
        ]
        # Buttons are compact-styled; the CSS makes them single-line.
        for b in buttons:
            assert b.compact is True


@skip_if_trio
@pytest.mark.anyio
async def test_card_applies_kind_class_per_option() -> None:
    """Each button carries the ``kind-<option.kind>`` CSS class for colour."""
    pending = _pending(
        options=[
            PermissionOption(option_id="approve", name="Approve", kind="allow_once"),
            PermissionOption(
                option_id="terminate", name="Terminate", kind="reject_always"
            ),
        ]
    )
    async with _CardApp(pending).run_test() as pilot:
        approve_btn = pilot.app.query_one(f"#{_BUTTON_ID_PREFIX}approve", Button)
        terminate_btn = pilot.app.query_one(f"#{_BUTTON_ID_PREFIX}terminate", Button)
        assert "kind-allow-once" in approve_btn.classes
        assert "kind-reject-always" in terminate_btn.classes


# ---------------------------------------------------------------------------
# Press → bubble
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_pressing_approve_bubbles_decision_with_tool_call_id() -> None:
    """Click Approve → ApprovalDecisionRequested(tool_call_id, "approve")."""
    pending = _pending(tool_call_id="tc-xyz")
    app = _CardApp(pending)
    async with app.run_test() as pilot:
        await pilot.click(f"#{_BUTTON_ID_PREFIX}approve")
        await pilot.pause()
    assert len(app.bubbles) == 1
    bubble = app.bubbles[0]
    assert bubble.tool_call_id == "tc-xyz"
    assert bubble.option_id == "approve"


@skip_if_trio
@pytest.mark.anyio
async def test_pressing_reject_bubbles_decision_with_reject_option_id() -> None:
    """Click Reject → bubble carries ``option_id == "reject"``."""
    pending = _pending()
    app = _CardApp(pending)
    async with app.run_test() as pilot:
        await pilot.click(f"#{_BUTTON_ID_PREFIX}reject")
        await pilot.pause()
    assert len(app.bubbles) == 1
    assert app.bubbles[0].option_id == "reject"
