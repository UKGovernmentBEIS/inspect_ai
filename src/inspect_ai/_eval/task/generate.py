from typing import Literal

from inspect_ai.model import (
    CachePolicy,
    GenerateConfig,
    Model,
    ToolFunction,
    ToolInfo,
)
from inspect_ai.model._cache import epoch
from inspect_ai.solver import TaskState, Tool
from inspect_ai.solver._tool.call_tools import call_tools
from inspect_ai.solver._tool.tool_def import tool_defs


async def task_generate(
    model: Model,
    state: TaskState,
    tool_calls: Literal["loop", "single", "none"],
    cache: bool | CachePolicy,
    config: GenerateConfig,
) -> TaskState:
    # track tool_choice (revert to "auto" after first forced call of a tool)
    tool_choice = state.tool_choice

    while True:
        # If we don't update the epoch here as we go, it's entirely possible
        # we'd cache the same response for every single epoch, which would
        # completely defeat the point!
        epoch.set(state.epoch)

        # call the model
        state.output = await model.generate(
            input=state.messages,
            tools=tools_info(state.tools),
            tool_choice=tool_choice,
            config=config,
            cache=cache,
        )

        # append the assistant message
        message = state.output.choices[0].message
        state.messages.append(message)

        # check for completed
        if state.completed:
            return state

        # resolve tool calls if necessary
        if tool_calls != "none" and state.tool_calls_pending:
            # call tools
            state = await call_tools(state)

            # check for completed or only executing a single tool call
            if state.completed or tool_calls == "single":
                return state

            # if a tool_call was forced set tool_choice to 'auto'
            # (otherwise it will get forced over and over again)
            if isinstance(tool_choice, ToolFunction):
                tool_choice = "auto"

        # no tool calls or not resolving tool calls, we are done!
        else:
            return state


def tools_info(tools: list[Tool]) -> list[ToolInfo]:
    tdefs = tool_defs(tools)
    return [
        ToolInfo(name=tool.name, description=tool.description, params=tool.params)
        for tool in tdefs
    ]
