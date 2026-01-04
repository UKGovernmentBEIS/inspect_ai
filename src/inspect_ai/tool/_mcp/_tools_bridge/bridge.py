"""Bridge for exposing host-side tools via MCP in sandbox."""

from collections.abc import Sequence
from dataclasses import dataclass

from inspect_ai.tool import Tool


@dataclass
class BridgedToolsSpec:
    """Specification for host-side tools to expose via MCP bridge.

    This allows Inspect tools defined on the host to be exposed to agents
    running inside a sandbox via MCP.

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
