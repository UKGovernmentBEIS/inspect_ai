from contextlib import AsyncExitStack
from copy import deepcopy
from typing import Sequence

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_info,
    set_registry_info,
)
from inspect_ai.tool._mcp._types import MCPServer

from ._agent import AGENT_DESCRIPTION, Agent, AgentState
from ._agent import agent as agent_decorator


def agent_with(
    agent: Agent,
    *,
    name: str | None = None,
    description: str | None = None,
    mcp_servers: MCPServer | Sequence[MCPServer] | None = None,
) -> Agent:
    """Agent with modifications to name and/or description

    This function modifies the passed agent in place and
    returns it (possibly with a wrapper for starting and
    stopping `mcp_servers`). If you want to create multiple
    variations of a single agent using `agent_with()` you
    should create the underlying agent multiple times.

    Args:
       agent: Agent instance.
       name: Agent name (optional).
       description: Agent description (optional).
       mcp_servers: Model Context Protcol servers to
          start/stop when executing the agent.

    Returns:
       The passed agent with the requested modifications.
    """
    # resolve name and description
    if is_registry_object(agent):
        info = registry_info(agent)
        name = name or info.name
        description = description or info.metadata.get(AGENT_DESCRIPTION, None)

    # if the name is null then raise
    if name is None:
        raise ValueError("You must provide a name to agent_with")

    # resolve mcp servers
    mcp_servers = (
        mcp_servers
        if isinstance(mcp_servers, Sequence)
        else None
        if mcp_servers is None
        else [mcp_servers]
    )

    # provide mcp server wrappers if requested
    if mcp_servers is not None:

        @agent_decorator(name=name)
        def agent_with_mcp_servers() -> Agent:
            async def execute(state: AgentState) -> AgentState:
                async with AsyncExitStack() as exit_stack:
                    # connect to servers
                    for mcp_server in deepcopy(mcp_servers):
                        await exit_stack.enter_async_context(mcp_server)

                    # run the agent
                    state = await agent(state)

                # return updated state
                return state

            return execute

        # agent wrapped with mcp server startup/shutdown
        agent = agent_with_mcp_servers()

    # now set registry info
    set_registry_info(
        agent,
        RegistryInfo(
            type="agent",
            name=name,
            metadata={AGENT_DESCRIPTION: description}
            if description is not None
            else {},
        ),
    )

    # all done!
    return agent
