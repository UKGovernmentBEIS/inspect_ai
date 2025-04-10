from rich.prompt import Prompt

from inspect_ai._util.transcript import transcript_panel
from inspect_ai.tool._tool_call import ToolCallView
from inspect_ai.util._console import input_screen

from .._approval import Approval, ApprovalDecision
from .util import (
    HUMAN_APPROVED,
    HUMAN_ESCALATED,
    HUMAN_REJECTED,
    HUMAN_TERMINATED,
    render_tool_approval,
)


def console_approval(
    message: str, view: ToolCallView, choices: list[ApprovalDecision]
) -> Approval:
    with input_screen(width=None) as console:
        console.print(
            transcript_panel(
                title="Approve Tool", content=render_tool_approval(message, view)
            )
        )

        # provide choices
        prompts: dict[str, str] = {}
        for choice in choices:
            prompts[choice[0]] = f"{choice.capitalize()} ({choice[0]})"
        values = list(prompts.values())
        prompt = ", ".join(values[:-1])
        prompt = f"{prompt}, or {values[-1]}"

        def render_approval(approval: Approval) -> Approval:
            console.print(f"Decision: {approval.decision.capitalize()}")
            return approval

        while True:
            decision = Prompt.ask(
                prompt=prompt,
                console=console,
                choices=list(prompts.keys()),
                default="a",
            ).lower()

            if decision == "a":
                return render_approval(
                    Approval(decision="approve", explanation=HUMAN_APPROVED)
                )
            elif decision == "r":
                return render_approval(
                    Approval(decision="reject", explanation=HUMAN_REJECTED)
                )
            elif decision == "t":
                return render_approval(
                    Approval(decision="terminate", explanation=HUMAN_TERMINATED)
                )
            elif decision == "e":
                return render_approval(
                    Approval(decision="escalate", explanation=HUMAN_ESCALATED)
                )
