from functools import wraps
from typing import Any

from inspect_ai.agent._agent import Agent
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool import Tool, ToolResult, tool


@solver
def agent_as_solver(agent: Agent) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        messages, output = await agent(state.messages)
        state.messages = messages
        if output is not None:
            state.output = output
        return state

    return solve


@tool
def agent_as_tool(agent: Agent) -> Tool:
    @wraps(agent)
    async def execute(input: str, *args: Any, **kwargs: Any) -> ToolResult:
        messages = await agent([ChatMessageUser(content=input)], *args, **kwargs)
        if isinstance(messages[-1], ChatMessageAssistant):
            return messages[-1].content
        else:
            return ""

    return execute
