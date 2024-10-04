from rich.panel import Panel
from rich.prompt import Prompt

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._console import input_screen

from ._approval import Approval
from ._approver import Approver
from ._registry import approver


@approver(name="human")
def human_approver() -> Approver:
    """Interactive human approver.

    Returns:
       Approver: Interactive human approver.
    """

    async def approve(
        tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        with input_screen() as console:
            console.print(
                Panel(
                    f"Tool: {tool_call.function}\nArguments: {tool_call.arguments}",
                    title="Approval Request",
                    subtitle="Current State",
                )
            )

            decision = Prompt.ask(
                "[bold]Approve (y), Reject (r), Escalate (e), or Terminate (t)?[/bold]",
                choices=["y", "r", "e", "t"],
                default="e",
            )

        if decision == "y":
            return Approval(
                decision="approve", explanation="Approved by human approver."
            )
        elif decision == "r":
            return Approval(
                decision="reject", explanation="Rejected by human approver."
            )
        elif decision == "e":
            return Approval(
                decision="escalate", explanation="Escalated by human approver."
            )
        elif decision == "t":
            return Approval(
                decision="terminate", explanation="Terminated by human approver."
            )
        return Approval(
            decision="escalate",
            explanation="Invalid input from human approver, escalating.",
        )

    return approve
