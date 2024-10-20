from inspect_ai.tool import Tool, ToolChoice
from inspect_ai.tool._tool_def import ToolDef

from ._solver import Generate, Solver, solver
from ._task_state import TaskState


@solver
def use_tools(
    *tools: Tool | list[Tool],
    tool_choice: ToolChoice | None = "auto",
) -> Solver:
    """
    Inject tools into the task state to be used in generate().

    Args:
        *tools (Tool | list[Tool]): One or more tools or lists of tools
          to make available to the model. If no tools are passed, then
          no change to the currently available set of `tools` is made.
        tool_choice (ToolChoice | None): Directive indicating which
          tools the model should use. If `None` is passed, then no
          change to `tool_choice` is made.

    Returns:
        A solver that injects the tools and tool_choice into the task state.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # build up tools
        tools_update: list[Tool] = []

        # add tool function to take care of tool/tool_def
        def add_tool(tool: Tool | ToolDef) -> None:
            if isinstance(tool, ToolDef):
                tool = tool.as_tool()
            tools_update.append(tool)

        for tool in tools:
            if isinstance(tool, list):
                for t in tool:
                    add_tool(t)
            else:
                add_tool(tool)
        if len(tools_update) > 0:
            state.tools = tools_update

        # set tool choice if specified
        if tool_choice is not None:
            state.tool_choice = tool_choice

        # return state
        return state

    return solve
