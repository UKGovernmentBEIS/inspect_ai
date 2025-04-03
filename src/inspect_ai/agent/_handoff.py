from typing import Any, Sequence

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_unqualified_name,
    set_registry_info,
)
from inspect_ai.tool._tool import Tool, ToolResult, ToolSource
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_description import ToolDescription, set_tool_description

from ._agent import Agent
from ._as_tool import agent_tool_info
from ._filter import MessageFilter


def handoff(
    agent: Agent,
    description: str | None = None,
    input_filter: MessageFilter | None = None,
    output_filter: MessageFilter | None = None,
    tool_name: str | None = None,
    **agent_kwargs: Any,
) -> Tool:
    """Create a tool that enables models to handoff to agents.

    Args:
        agent: Agent to hand off to.
        description: Handoff tool description (defaults to agent description)
        input_filter: Filter to modify the message history before calling the tool.
            Use the built-in `remove_tools` filter to remove all tool calls
            or alternatively specify a custom `MessageFilter` function.
        output_filter: Filter to modify the message history after calling the tool.
            Use the built-in `last_message` filter to return only the last message
            or alternatively specify a custom `MessageFilter` function.
        tool_name: Alternate tool name (defaults to `transfer_to_{agent_name}`)
        **agent_kwargs: Arguments to curry to `Agent` function (arguments provided here
            will not be presented to the model as part of the tool interface).

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
    tool_info = agent_tool_info(agent, description, **agent_kwargs)

    # AgentTool calls will be intercepted by execute_tools
    agent_tool = AgentTool(agent, input_filter, output_filter, **agent_kwargs)
    tool_name = tool_name or f"transfer_to_{tool_info.name}"
    set_registry_info(agent_tool, RegistryInfo(type="tool", name=tool_name))
    set_tool_description(
        agent_tool,
        ToolDescription(
            name=tool_name,
            description=tool_info.description,
            parameters=tool_info.parameters,
        ),
    )
    return agent_tool


class AgentTool(Tool):
    def __init__(
        self,
        agent: Agent,
        input_filter: MessageFilter | None = None,
        output_filter: MessageFilter | None = None,
        **kwargs: Any,
    ):
        self.agent = agent
        self.input_filter = input_filter
        self.output_filter = output_filter
        self.kwargs = kwargs

    @property
    def __name__(self) -> str:
        return registry_unqualified_name(self.agent)

    async def __call__(self) -> ToolResult:
        raise RuntimeError("AgentTool should not be called directly")


def has_handoff(
    tools: Sequence[Tool | ToolDef | ToolSource] | None,
) -> bool:
    if tools:
        return any([isinstance(tool, AgentTool) for tool in tools])
    else:
        return False
