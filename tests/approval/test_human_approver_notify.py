"""Tests that the human approver fires `notify()` for out-of-band pings.

Regardless of which surface (ACP / panel / console) ultimately collects
the operator's response, the approver should emit an Apprise notification
when one is configured.
"""

from unittest.mock import MagicMock

import pytest

from inspect_ai.approval._approval import Approval
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._notify import apprise_scope


async def test_human_approver_fires_notify_via_apprise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Short-circuit each surface so the approver returns without UI.
    from inspect_ai.approval._human import approver as approver_module

    async def fake_acp_request(**kwargs: object) -> Approval | None:
        return None

    async def fake_panel(*args: object, **kwargs: object) -> Approval:
        raise NotImplementedError

    def fake_console(*args: object, **kwargs: object) -> Approval:
        return Approval(decision="approve")

    # Patch the bindings inside approver.py — the module imports these
    # symbols by name at module load, so we have to patch the bindings
    # in approver.py rather than in their source modules.
    monkeypatch.setattr(
        approver_module, "request_human_approval_via_acp", fake_acp_request
    )
    monkeypatch.setattr(approver_module, "panel_approval", fake_panel)
    monkeypatch.setattr(approver_module, "console_approval", fake_console)

    fake_apprise = MagicMock()
    fake_apprise.notify = MagicMock(return_value=True)

    call = ToolCall(id="t1", function="dangerous_op", arguments={})
    view = ToolCallView()
    approver = human_approver()
    with apprise_scope(fake_apprise):
        result = await approver(
            "Run dangerous_op?",
            call,
            view,
            [],
        )

    assert result.decision == "approve"
    fake_apprise.notify.assert_called_once()
    kwargs = fake_apprise.notify.call_args.kwargs
    # No active sample in this test → default title is `Inspect Agent`
    # and the body is the unmodified approval message.
    assert kwargs.get("body") == "Run dangerous_op?"
    assert kwargs.get("title") == "Inspect Agent"
