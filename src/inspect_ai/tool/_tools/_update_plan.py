from pydantic import BaseModel, Field

from .._tool import Tool, tool
from .._tool_def import ToolDef


class PlanStep(BaseModel):
    step: str = Field(description="Step name.")
    status: str = Field(description="One of: pending, in_progress, completed")


@tool
def update_plan(description: str | None = None) -> Tool:
    """Planning tool to track steps and progress in a longer horizon task.

    The update_plan tool is based on the update_plan provided by [Codex CLI](https://github.com/openai/codex).

    The default tool description is taken from the GPT 5.1 system prompt for Codex. Pass a custom `description` to override this.

    Args:
        description: Override the default description of the update_plan tool.
    """

    async def execute(plan: list[PlanStep], explanation: str | None = None) -> str:
        """Update the task plan.

        You have access to an update_plan tool which tracks steps and progress and renders them to the user. Using the tool helps demonstrate that you've understood the task and convey how you're approaching it. Plans can help to make complex, ambiguous, or multi-phase work clearer and more collaborative for the user. A good plan should break the task into meaningful, logically ordered steps that are easy to verify as you go.

        Provide an optional explanation and a list of plan items, each with a step and status. At most one step can be in_progress at a time.

        Note that plans are not for padding out simple work with filler steps or stating the obvious. The content of your plan should not involve doing anything that you aren't capable of doing (i.e. don't try to test things that you can't test). Do not use plans for simple or single-step queries that you can just do or answer immediately.

        Do not repeat the full contents of the plan after an update_plan call — the harness already displays it. Instead, summarize the change made and highlight any important context or next step.

        Before running a command, consider whether or not you have completed the previous step, and make sure to mark it as completed before moving on to the next step. It may be the case that you complete all steps in your plan after a single pass of implementation. If this is the case, you can simply mark all the planned steps as completed. Sometimes, you may need to change plans in the middle of a task: call update_plan with the updated plan and make sure to provide an explanation of the rationale when doing so.

        Maintain statuses in the tool: exactly one item in_progress at a time; mark items complete when done; post timely status transitions. Do not jump an item from pending to completed: always set it to in_progress first. Do not batch-complete multiple items after the fact. Finish with all items completed or explicitly canceled/deferred before ending the turn. Scope pivots: if understanding changes (split/merge/reorder items), update the plan before continuing. Do not let the plan go stale while coding.

        Use a plan when:

        - The task is non-trivial and will require multiple actions over a long time horizon.
        - There are logical phases or dependencies where sequencing matters.
        - The work has ambiguity that benefits from outlining high-level goals.
        - You want intermediate checkpoints for feedback and validation.
        - When the user asked you to do more than one thing in a single prompt
        - The user has asked you to use the plan tool (aka "TODOs")
        - You generate additional steps while working, and plan to do them before yielding to the user

        ### Examples

        High-quality plans

        Example 1:
        - Add CLI entry with file args
        - Parse Markdown via CommonMark library
        - Apply semantic HTML template
        - Handle code blocks, images, links
        - Add error handling for invalid files

        Example 2:
        - Define CSS variables for colors
        - Add toggle with localStorage state
        - Refactor components to use variables
        - Verify all views for readability
        - Add smooth theme-change transition

        Example 3:
        - Set up Node.js + WebSocket server
        - Add join/leave broadcast events
        - Implement messaging with timestamps
        - Add usernames + mention highlighting
        - Persist messages in lightweight DB
        - Add typing indicators + unread count

        Low-quality plans

        Example 1:
        - Create CLI tool
        - Add Markdown parser
        - Convert to HTML

        Example 2:
        - Add dark mode toggle
        - Save preference
        - Make styles look good

        Example 3:
        - Create single-file HTML game
        - Run quick sanity check
        - Summarize usage instructions

        If you need to write a plan, only write high quality plans, not low quality ones.

        Args:
            plan: The list of steps.
            explanation: Optional explanation.
        """
        return "Plan updated"

    return ToolDef(
        execute,
        name="update_plan",
        description=description,
    ).as_tool()
