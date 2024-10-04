from re import Pattern
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approver import Approval, Approver

"""
approvers:
   - name: human
     tools: [bash, python, web_browser*]
     params:
        ansi: false

   - name: auto
     tools: *


"""


class ApprovalPolicy:
    approver: Approver
    tools: str | list[str]


def policy_approver(policies: list[ApprovalPolicy]) -> Approver:
    # compile policy into approvers and regexes for matching
    # policy_matchers: list[list[Pattern], Approver] = []

    # function to find

    async def approve(
        tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        return Approval(decision="approve")

    return approve
