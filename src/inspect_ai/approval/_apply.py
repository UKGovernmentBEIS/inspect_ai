import sys
from contextvars import ContextVar

from inspect_ai.model._call_tools import ToolDef
from inspect_ai.tool._tool_call import ToolCall

from ._approver import Approver
from ._policy import ApprovalPolicy, policy_approver


async def apply_tool_approval(
    tool_call: ToolCall, tool_def: ToolDef
) -> tuple[bool, str | None]:
    from inspect_ai.solver._task_state import sample_state

    approver = _tool_approver.get(None)
    if approver:
        approval = await approver(tool_call, "view", sample_state())
        match approval.decision:
            case "approve":
                return True, None
            case "reject":
                return False, approval.explanation
            case _:
                sys.exit(1)
    else:
        return True, None


def init_tool_approval(approval: list[ApprovalPolicy] | None) -> None:
    if approval:
        _tool_approver.set(policy_approver(approval))
    else:
        _tool_approver.set(None)


_tool_approver: ContextVar[Approver | None] = ContextVar("tool_approver", default=None)
