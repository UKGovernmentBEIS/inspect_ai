from typing import Callable

from inspect_ai._util.registry import registry_info
from inspect_ai.agent._agent import Agent
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._run import run
from inspect_ai.solver._solver import Solver
from inspect_ai.tool._tool import Tool, ToolResult
from inspect_ai.tool._tool_info import ToolInfo, parse_tool_info
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.tool._tool_with import tool_with


def handoff(
    agent: Solver | Agent,
    tool_name: str | None = None,
    tool_description: str | None = None,
    input_filter: Callable[[list[ChatMessage]], list[ChatMessage]] | None = None,
) -> Tool:
    """Create a tool that enables models to handoff to agents and solvers.

    Args:
        agent: Agent or solver to hand off to.
        tool_name: Alternate tool name (defaults to `handoff_to_{agent_name}`)
        tool_description: Alternate tool description: defaults to agent description.
        input_filter: Optional callable to modify the message history before calling the tool.

    Returns:
        Tool for handing off to the agent (must be called using `execute_tools()` to be
        properly handled)
    """
    # normalise to agent
    if isinstance(agent, Solver):
        solver = agent

        async def run_agent(
            messages: list[ChatMessage],
        ) -> tuple[list[ChatMessage], ModelOutput | None]:
            return await run(solver, messages)

        handoff_agent = run_agent
        tool_info = ToolInfo(
            name=registry_info(solver).name,
            description=parse_tool_info(solver).description,
            parameters=ToolParams(),
        )
    else:
        handoff_agent = agent
        tool_info = parse_tool_info(handoff_agent)
        del tool_info.parameters.properties["messages"]

    # we are going to intercept agent tool calls and do the
    # message / model output handling
    return tool_with(
        AgentTool(handoff_agent, input_filter),
        name=tool_name or f"handoff_to_{tool_info.name}",
        description=tool_description or tool_info.description,
        parameters=tool_info.parameters.model_dump(),
    )


class AgentTool(Tool):
    def __init__(
        self,
        agent: Agent,
        input_filter: Callable[[list[ChatMessage]], list[ChatMessage]] | None = None,
    ):
        self.agent = agent
        self.input_filter = input_filter

    async def __call__(self) -> ToolResult:
        raise RuntimeError("AgentTool should not be called directly")
