from typing import Any

from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tool_params import ToolParam

from ._agent import Agent, AgentState


@solver
def as_solver(agent: Agent) -> Solver:
    """Convert an agent to a solver.

    Note that agents used as solvers will only receive their first parameter
    (`input`). Any other parameters must provide appropriate defaults.

    Args:
       agent: Agent to convert.

    Solver:
       Solver from agent.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        agent_state = AgentState(messages=state.messages, output=state.output)
        agent_state = await agent(agent_state)
        state.messages = agent_state.messages
        state.output = agent_state.output
        return state

    return solve


@tool
def as_tool(agent: Agent) -> Tool:
    """Convert an agent to a tool.

    Args:
        agent: Agent to convert.

    Returns:
        Tool from agent.
    """

    async def execute(input: str, *args: Any, **kwargs: Any) -> ToolResult:
        state = AgentState(
            messages=[ChatMessageUser(content=input)], output=ModelOutput()
        )
        state = await agent(state, *args, **kwargs)
        if len(state.messages) > 0 and isinstance(
            state.messages[-1], ChatMessageAssistant
        ):
            return state.messages[-1].content
        else:
            return ""

    tool_info = parse_tool_info(agent)
    del tool_info.parameters.properties["state"]
    tool_info.parameters.properties["input"] = ToolParam(
        type="string", description="Input message."
    )
    tool_def = ToolDef(
        execute,
        name=tool_info.name,
        description=tool_info.description,
        parameters=tool_info.parameters,
    )
    return tool_def.as_tool()
