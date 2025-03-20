from typing import Any, Awaitable, Callable, TypeAlias

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_unqualified_name,
    set_registry_info,
)
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_description import ToolDescription, set_tool_description

from ._agent import Agent
from ._as_tool import agent_tool_info

HandoffFilter: TypeAlias = Callable[[list[ChatMessage]], Awaitable[list[ChatMessage]]]
"""Function used for filtering agent input and output messages."""


def handoff(
    agent: Agent,
    tool_name: str | None = None,
    tool_description: str | None = None,
    input_filter: HandoffFilter | None = None,
    **agent_kwargs: Any,
) -> Tool:
    """Create a tool that enables models to handoff to agents.

    Args:
        agent: Agent to hand off to.
        tool_name: Alternate tool name (defaults to `handoff_to_{agent_name}`)
        tool_description: Alternate tool description: defaults to agent description.
        input_filter: Optional callable to modify the message history before calling the tool.
        **agent_kwargs: Arguments to curry to Agent function (arguments provided here will not be presented to the model as part of the tool interface).


    Returns:
        Tool for handing off to the agent (must be called using `execute_tools()` to be
        properly handled)
    """
    # agent must be registered (so we can get its name)
    if not is_registry_object(agent):
        raise RuntimeError(
            "Agent passed to as_tool was not created by an @agent decorated function"
        )

    # get tool_info
    tool_info = agent_tool_info(agent, **agent_kwargs)

    # AgentTool calls will be intercepted by execute_tools
    agent_tool = AgentTool(agent, input_filter, **agent_kwargs)
    tool_name = tool_name or f"handoff_to_{tool_info.name}"
    set_registry_info(agent_tool, RegistryInfo(type="tool", name=tool_name))
    set_tool_description(
        agent_tool,
        ToolDescription(
            name=tool_name,
            description=tool_description or tool_info.description,
            parameters=tool_info.parameters,
        ),
    )
    return agent_tool


@tool
class AgentTool(Tool):
    def __init__(
        self,
        agent: Agent,
        input_filter: HandoffFilter | None = None,
        **kwargs: Any,
    ):
        self.agent = agent
        self.input_filter = input_filter
        self.kwargs = kwargs

    @property
    def __name__(self) -> str:
        return registry_unqualified_name(self.agent)

    async def __call__(self) -> ToolResult:
        raise RuntimeError("AgentTool should not be called directly")
