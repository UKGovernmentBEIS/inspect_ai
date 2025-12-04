"""Host-side sandbox service for executing bridged tools."""

import json
from typing import Any

import anyio

from inspect_ai.tool import Tool
from inspect_ai.util._sandbox import SandboxEnvironment
from inspect_ai.util._sandbox.service import sandbox_service

SERVICE_NAME = "tools_bridge"


async def run_tools_bridge_service(
    sandbox: SandboxEnvironment,
    tools: dict[str, Tool],
    instance: str,
    started: anyio.Event,
) -> None:
    """Run sandbox service that executes tools on the host.

    This service receives tool call requests from the MCP server running
    in the sandbox, executes the corresponding Inspect tool, and returns
    the result.

    Args:
        sandbox: The sandbox environment to publish service to
        tools: Dictionary mapping tool names to tool instances
        instance: Unique instance ID for this service
        started: Event to signal when service is ready
    """

    async def call_tool(tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return the result as a string."""
        if tool_name not in tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool = tools[tool_name]
        result = await tool(**arguments)

        # MCP returns strings, so serialize if needed
        if isinstance(result, str):
            return result
        return json.dumps(result)

    await sandbox_service(
        name=SERVICE_NAME,
        methods={"call_tool": call_tool},
        until=lambda: False,
        sandbox=sandbox,
        instance=instance,
        started=started,
    )
