from inspect_ai.model import (
    ChatMessageSystem,
    ToolChoice,
)

from .._solver import Generate, Solver, TaskState, solver
from .._util import append_system_message
from .tool import Tool
from .tool_def import tool_defs


@solver
def use_tools(
    tools: Tool | list[Tool] | None = None, tool_choice: ToolChoice = "auto"
) -> Solver:
    """
    Solver that inject tools into the task state to be used in generate().

    Args:
        tools (Tool | list[Tool]): one or more tools to inject into the task state.
        tool_choice (ToolChoice | None): Directive indicating which
          tools the model should use.

    Returns:
        A solver that injects the tools and tool_choice into the task state.
    """
    # create tool defs
    tools = tools if isinstance(tools, list) else [tools] if tools else None
    tdefs = tool_defs(tools) if tools else None

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # register the tools
        if tools and tdefs:
            state.tools.extend(tools)

            # append the tools system prompts. mark the 'source' of messages
            # as tool so they can be removed if tool_choice == "none"
            for tool in tdefs:
                if tool.prompt:
                    append_system_message(
                        state.messages,
                        ChatMessageSystem(content=tool.prompt, tool=tool.name),
                    )

        # set tool choice (note you can call this function w/o tools
        # for just the side effect of enabling/disabling tool usage)
        state.tool_choice = tool_choice

        # return state
        return state

    return solve
