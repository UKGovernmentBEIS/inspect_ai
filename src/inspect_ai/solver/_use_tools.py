from inspect_ai.tool import Tool, ToolChoice

from ._solver import Generate, Solver, solver
from ._task_state import TaskState


@solver
def use_tools(
    tools: Tool | list[Tool] | None = None, tool_choice: ToolChoice | None = "auto"
) -> Solver:
    """
    Inject tools into the task state to be used in generate().

    Args:
        tools (Tool | list[Tool] | None): One or more tools to make available
          to the model. If `None` is passed, then no change to the currently
          available set of `tools` is made.
        tool_choice (ToolChoice | None): Directive indicating which
          tools the model should use. If `None` is passed, then no
          change to `tool_choice` is made.

    Returns:
        A solver that injects the tools and tool_choice into the task state.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # set tools if specified
        if tools is not None:
            state.tools = tools if isinstance(tools, list) else [tools]

        # set tool choice if specified
        if tool_choice is not None:
            state.tool_choice = tool_choice

        # return state
        return state

    return solve
