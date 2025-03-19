from typing import Any

from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_def import ToolDef
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
