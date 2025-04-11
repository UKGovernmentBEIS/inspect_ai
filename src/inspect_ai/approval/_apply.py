from contextvars import ContextVar

from inspect_ai._util.format import format_function_call
from inspect_ai.approval._approval import Approval
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
)

from ._approver import Approver
from ._policy import ApprovalPolicy, policy_approver


async def apply_tool_approval(
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> tuple[bool, Approval | None]:
    approver = _tool_approver.get(None)
    if approver:
        # resolve view
        if viewer:
            view = viewer(call)
            if not view.call:
                view.call = default_tool_call_viewer(call).call
        else:
            view = default_tool_call_viewer(call)

        # call approver
        approval = await approver(
            message=message,
            call=call,
            view=view,
            history=history,
        )

        # process decision
        match approval.decision:
            case "approve" | "modify":
                return True, approval
            case "reject":
                return False, approval
            case "terminate":
                return False, approval
            case "escalate":
                raise RuntimeError("Unexpected 'escalate' from policy approver.")

    # no approval system registered
    else:
        return True, None


def default_tool_call_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(
            format="markdown",
            content="```python\n"
            + format_function_call(call.function, call.arguments)
            + "\n```\n",
        )
    )


def init_tool_approval(approval: list[ApprovalPolicy] | None) -> None:
    if approval:
        _tool_approver.set(policy_approver(approval))
    else:
        _tool_approver.set(None)


def have_tool_approval() -> bool:
    return _tool_approver.get(None) is not None


_tool_approver: ContextVar[Approver | None] = ContextVar("tool_approver", default=None)
