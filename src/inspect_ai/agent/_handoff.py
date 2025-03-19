from typing import Awaitable, Callable, TypeAlias

from inspect_ai.agent._agent import Agent
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool import Tool, ToolResult
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tool_with import tool_with

HandoffFilter: TypeAlias = Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]]
"""Function used for filtering agent input and output messages."""


def handoff(
    agent: Agent,
    tool_name: str | None = None,
    tool_description: str | None = None,
    input_filter: HandoffFilter | None = None,
) -> Tool:
    """Create a tool that enables models to handoff to agents and solvers.

    Args:
        agent: Agent to hand off to.
        tool_name: Alternate tool name (defaults to `handoff_to_{agent_name}`)
        tool_description: Alternate tool description: defaults to agent description.
        input_filter: Optional callable to modify the message history before calling the tool.

    Returns:
        Tool for handing off to the agent (must be called using `execute_tools()` to be
        properly handled)
    """
    # normalise to agent
    tool_info = parse_tool_info(agent)
    del tool_info.parameters.properties["messages"]

    # AgentTool calls will be intercepted by execute_tools
    return tool_with(
        AgentTool(agent, input_filter),
        name=tool_name or f"handoff_to_{tool_info.name}",
        description=tool_description or tool_info.description,
        parameters=tool_info.parameters.model_dump(),
    )


class AgentTool(Tool):
    def __init__(
        self,
        agent: Agent,
        input_filter: HandoffFilter | None = None,
    ):
        self.agent = agent
        self.input_filter = input_filter

    async def __call__(self) -> ToolResult:
        raise RuntimeError("AgentTool should not be called directly")
