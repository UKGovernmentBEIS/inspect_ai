from typing import Sequence

from inspect_ai.tool import Tool, ToolChoice
from inspect_ai.tool._tool import ToolSource
from inspect_ai.tool._tool_def import ToolDef

from ._solver import Generate, Solver, solver
from ._task_state import TaskState


@solver
def use_tools(
    *tools: Tool | ToolDef | ToolSource | Sequence[Tool | ToolDef | ToolSource],
    tool_choice: ToolChoice | None = "auto",
    append: bool = False,
) -> Solver:
    """
    Inject tools into the task state to be used in generate().

    Args:
      *tools: One or more tools or lists of tools
        to make available to the model. If no tools are passed, then
        no change to the currently available set of `tools` is made.
      tool_choice: Directive indicating which
        tools the model should use. If `None` is passed, then no
        change to `tool_choice` is made.
      append: If `True`, then the passed-in tools are appended
        to the existing tools; otherwise any existing tools are
        replaced (the default)

    Returns:
        A solver that injects the tools and tool_choice into the task state.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # build up tools
        tools_update: list[Tool] = []

        # add tool function to take care of tool/tool_def
        async def add_tools(tool: Tool | ToolDef | ToolSource) -> None:
            if isinstance(tool, ToolSource):
                tools_update.extend(await tool.tools())
            else:
                if isinstance(tool, ToolDef):
                    tool = tool.as_tool()
                tools_update.append(tool)

        for tool in tools:
            if isinstance(tool, Sequence):
                for t in tool:
                    await add_tools(t)
            else:
                await add_tools(tool)
        if len(tools_update) > 0:
            if append:
                existing_tools = state.tools
                state.tools = existing_tools + tools_update
            else:
                state.tools = tools_update

        # set tool choice if specified
        if tool_choice is not None:
            state.tool_choice = tool_choice

        # return state
        return state

    return solve
