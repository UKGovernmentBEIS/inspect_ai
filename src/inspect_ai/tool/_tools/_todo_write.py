from typing import Literal

from pydantic import BaseModel, Field

from .._tool import Tool, tool


class TodoStep(BaseModel):
    content: str = Field(description="Step description.")
    status: Literal["pending", "in_progress", "completed"] = Field(
        description="One of: pending, in_progress, completed"
    )


@tool
def todo_write() -> Tool:
    """Planning tool to track steps and progress in longer horizon tasks.

    The todo_write tool helps agents organize complex, multi-step work by
    maintaining a structured task list with status tracking. The tool
    description synthesizes best practices from Claude Code and Codex CLI.
    """

    async def execute(todos: list[TodoStep], explanation: str | None = None) -> str:
        """Update the task plan.

        Use this tool to create and manage a structured task list for tracking progress on complex work. A good plan breaks the task into meaningful, logically ordered steps that are easy to verify as you go.

        Provide a list of todo items, each with content and status. Optionally provide an explanation when making significant changes to the plan.

        ## When to Use

        - The task requires multiple actions or has logical phases where sequencing matters.
        - The work has ambiguity that benefits from outlining high-level goals.
        - The user has asked you to do more than one thing in a single prompt.
        - You generate additional steps while working and plan to do them before finishing.

        ## When NOT to Use

        - The task is a single straightforward action.
        - The work is trivial or can be completed in fewer than 3 steps.
        - The task is purely conversational or informational.

        Do not pad out simple work with filler steps or state the obvious. The content of your plan should not involve doing anything that you aren't capable of doing. Aim for 3-7 items unless the task genuinely needs more.

        ## Status Management

        - **pending**: Step not yet started.
        - **in_progress**: Currently working on this step.
        - **completed**: Step finished successfully.

        Update status in real-time as you work. Mark a step as in_progress before beginning it, and completed immediately after finishing — don't batch completions after the fact. Never jump a step from pending directly to completed.

        Only mark a step as completed when you have fully accomplished it. Never mark a step as completed if:

        - Errors remain unresolved.
        - The implementation is partial or untested.
        - You encountered blockers you haven't worked around.

        If you cannot finish a step, keep it as in_progress and note the issue.

        Remove steps that are no longer relevant from the list entirely. If understanding changes mid-task, update the plan before continuing and provide an explanation of the rationale.

        Do not repeat the full contents of the plan after calling this tool — the harness already displays it. Instead, summarize the change and highlight any important context or next step.

        ## Plan Quality

        High-quality plans:

        - Identify relevant sources, inputs, and constraints to inspect
        - Evaluate each candidate approach against the task requirements
        - Cross-check important findings against available evidence
        - Summarize conclusions, remaining uncertainty, and next action

        Low-quality plans:

        - Look things up
        - Compare options
        - Write summary

        If you need to write a plan, only write high quality plans, not low quality ones.

        Args:
            todos: The list of steps.
            explanation: Optional explanation of changes to the plan.
        """
        return "Plan updated"

    return execute
