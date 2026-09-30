"""Bridge for exposing host-side tools via MCP in sandbox."""

from collections.abc import Sequence
from dataclasses import dataclass

from inspect_ai.tool import Tool


@dataclass
class BridgedToolsSpec:
    """Specification for host-side tools to expose via MCP bridge.

    This allows Inspect tools defined on the host to be exposed to agents
    running inside a sandbox via MCP.

    A bridged tool executes only for a call the model proposed in a bridged
    generation, once per proposal: each tool call in a model response handed
    to the agent grants one execution of exactly that tool with exactly those
    arguments, and a `tools/call` with no matching grant is denied with an
    error the agent surfaces to the model. An agent that retries a
    `tools/call` after a transport failure is therefore denied and should let
    the model re-propose the call. Set `require_proposal=False` for an agent
    that legitimately calls a host tool outside a model turn.

    Example:
        ```python
        from inspect_ai.tool import tool
        from inspect_ai.agent import BridgedToolsSpec, sandbox_agent_bridge

        @tool
        def my_tool():
            async def execute(query: str) -> str:
                \"\"\"Search database.\"\"\"
                return f"Results for: {query}"
            return execute

        async with sandbox_agent_bridge(
            bridged_tools=[BridgedToolsSpec(name="my_tools", tools=[my_tool()])]
        ) as bridge:
            # bridge.mcp_server_configs contains resolved MCPServerConfigHTTP
            pass
        ```
    """

    name: str
    """Name of the MCP server (visible to agent as mcp__{name}_*)."""

    tools: Sequence[Tool]
    """Inspect Tool objects to expose via MCP."""

    require_proposal: bool = True
    """Execute a tool only for a call the model proposed in a bridged generation.

    When `False`, any `tools/call` reaching this server executes, whether or not
    a model generation proposed it, so the bridge no longer guarantees that this
    server's tools run only for calls the model made. Use it for an agent that
    calls a host tool programmatically outside a model turn.
    """
