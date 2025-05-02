from typing import Any

from inspect_ai._util.registry import (
    is_registry_object,
    registry_info,
    registry_unqualified_name,
)
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_def import ToolDef, validate_tool_parameters
from inspect_ai.tool._tool_info import ToolInfo, parse_tool_info
from inspect_ai.tool._tool_params import ToolParam
from inspect_ai.util._limit import Limit, apply_limits
from inspect_ai.util._span import span

from ._agent import AGENT_DESCRIPTION, Agent, AgentState


@tool
def as_tool(
    agent: Agent,
    description: str | None = None,
    limits: list[Limit] = [],
    **agent_kwargs: Any,
) -> Tool:
    """Convert an agent to a tool.

    By default the model will see all of the agent's arguments as
    tool arguments (save for `state` which is converted to an `input`
    arguments of type `str`). Provide optional `agent_kwargs` to mask
    out agent parameters with default values (these parameters will
    not be presented to the model as part of the tool interface)

    Args:
       agent: Agent to convert.
       description: Tool description (defaults to agent description)
       limits: List of limits to apply to the agent. Should a limit
          be exceeded, the tool call ends and returns an error
          explaining that a limit was exceeded.
       **agent_kwargs: Arguments to curry to Agent function (arguments
          provided here will not be presented to the model as part
          of the tool interface).

    Returns:
        Tool from agent.
    """
    # agent must be registered (so we can get its name)
    if not is_registry_object(agent):
        raise RuntimeError(
            "Agent passed to as_tool was not created by an @agent decorated function"
        )

    # get tool_info
    tool_info = agent_tool_info(agent, description, **agent_kwargs)

    async def execute(input: str, *args: Any, **kwargs: Any) -> ToolResult:
        # prepare state
        state = AgentState(messages=[ChatMessageUser(content=input, source="input")])

        # run the agent with limits
        with apply_limits(limits):
            async with span(name=tool_info.name, type="agent"):
                state = await agent(state, *args, **(agent_kwargs | kwargs))

        # find assistant message to read content from (prefer output)
        if not state.output.empty:
            return state.output.message.content
        elif len(state.messages) > 0 and isinstance(
            state.messages[-1], ChatMessageAssistant
        ):
            return state.messages[-1].content
        else:
            return ""

    # add "input" param
    tool_info.parameters.properties = {
        "input": ToolParam(type="string", description="Input message.")
    } | tool_info.parameters.properties
    tool_info.parameters.required.append("input")

    # create tool
    tool_def = ToolDef(
        execute,
        name=tool_info.name,
        description=tool_info.description,
        parameters=tool_info.parameters,
    )
    return tool_def.as_tool()


def agent_tool_info(
    agent: Agent, description: str | None, **agent_kwargs: Any
) -> ToolInfo:
    # get tool_info and name
    tool_info = parse_tool_info(agent)
    tool_info.name = registry_unqualified_name(agent)

    # remove "state" param
    def remove_param(param: str) -> None:
        if param in tool_info.parameters.properties:
            del tool_info.parameters.properties[param]
        if param in tool_info.parameters.required:
            tool_info.parameters.required.remove(param)

    remove_param("state")

    # validate and remove curried params
    for agent_param in agent_kwargs.keys():
        if agent_param in tool_info.parameters.properties:
            remove_param(agent_param)
        else:
            raise ValueError(
                f"Agent {tool_info.name} does not have a '{agent_param}' parameter."
            )

    # resolve and validate description. the description in the call takes
    # precedence, then any @agent(description="<foo>"), and finally any
    # doc comment on the agent's execute function
    reg_info = registry_info(agent)
    tool_info.description = (
        description
        or reg_info.metadata.get(AGENT_DESCRIPTION, None)
        or tool_info.description
    )
    if len(tool_info.description) == 0:
        raise ValueError(
            f"Description not provided for agent function '{tool_info.name}'. Provide a "
            + "description either via @agent(description='<description>'), the description "
            + "argument to as_tool() or handoff(), or via a doc comment on the agent's "
            + "execute function."
        )

    # validate parameter descriptions and types
    validate_tool_parameters(tool_info.name, tool_info.parameters.properties)

    return tool_info
