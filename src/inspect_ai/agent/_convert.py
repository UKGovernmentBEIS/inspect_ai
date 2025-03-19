from typing import Any

from inspect_ai._util.registry import (
    is_registry_object,
    registry_unqualified_name,
)
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_def import ToolDef, validate_tool_parameters
from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tool_params import ToolParam

from ._agent import Agent, AgentState


@tool
def as_tool(agent: Agent) -> Tool:
    """Convert an agent to a tool.

    Args:
        agent: Agent to convert.

    Returns:
        Tool from agent.
    """
    # agent must be registered (so we can get its name)
    if not is_registry_object(agent):
        raise RuntimeError(
            "Agent passed to as_tool was not created by an @agent decorated function"
        )

    async def execute(input: str, *args: Any, **kwargs: Any) -> ToolResult:
        # prepare state and call agent
        state = AgentState(
            messages=[ChatMessageUser(content=input)], output=ModelOutput()
        )
        state = await agent(state, *args, **kwargs)

        # find assistant message to read content from (prefer output)
        if not state.output.empty:
            return state.output.message.content
        elif len(state.messages) > 0 and isinstance(
            state.messages[-1], ChatMessageAssistant
        ):
            return state.messages[-1].content
        else:
            return ""

    # get tool_info and name
    tool_info = parse_tool_info(agent)
    tool_info.name = registry_unqualified_name(agent)

    # remove "state" and replace with "input"
    del tool_info.parameters.properties["state"]
    tool_info.parameters.properties = {
        "input": ToolParam(type="string", description="Input message.")
    } | tool_info.parameters.properties
    tool_info.parameters.required.remove("state")
    tool_info.parameters.required.append("input")

    # confirm that we have descriptions for the tool and parameters
    if len(tool_info.description) == 0:
        raise ValueError(
            f"Description not provided for agent function '{tool_info.name}'"
        )

    # validate parameter descriptions and types
    validate_tool_parameters(tool_info.name, tool_info.parameters.properties)

    # create tool
    tool_def = ToolDef(
        execute,
        name=tool_info.name,
        description=tool_info.description,
        parameters=tool_info.parameters,
    )
    return tool_def.as_tool()
