"""Bridge for exposing host-side tools via MCP in sandbox."""

from collections.abc import Sequence
from dataclasses import dataclass

import anyio
from anyio.abc import TaskGroup
from shortuuid import uuid

from inspect_ai.tool import Tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._sandbox import SandboxEnvironment

from .._config import MCPServerConfigStdio
from .script_generator import generate_mcp_server_script
from .service import run_tools_bridge_service


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
            # bridge.mcp_server_configs contains resolved MCPServerConfigStdio
            pass
        ```
    """

    name: str
    """Name of the MCP server (visible to agent as mcp__{name}_*)."""

    tools: Sequence[Tool]
    """Inspect Tool objects to expose via MCP."""


async def setup_bridged_tools(
    sandbox: SandboxEnvironment,
    task_group: TaskGroup,
    spec: BridgedToolsSpec,
) -> MCPServerConfigStdio:
    """Set up MCP bridge for host-side tools.

    Starts a host-side service and writes an MCP server script to sandbox.
    Service runs until task_group is cancelled.

    Args:
        sandbox: The sandbox environment
        task_group: Task group for service lifecycle management
        spec: Specification for tools to bridge

    Returns:
        MCPServerConfigStdio that can be passed to CLI agents
    """
    tools_dict: dict[str, Tool] = {}
    tools_info: dict[str, ToolInfo] = {}

    for tool in spec.tools:
        tdef = ToolDef(tool)
        info = ToolInfo(
            name=tdef.name, description=tdef.description, parameters=tdef.parameters
        )
        tools_dict[info.name] = tool
        tools_info[info.name] = info

    # Generate unique instance ID
    instance = f"tools_bridge_{spec.name}_{uuid()}"

    # Start host-side service (runs until task_group cancelled)
    started = anyio.Event()
    task_group.start_soon(
        run_tools_bridge_service,
        sandbox,
        tools_dict,
        instance,
        started,
    )
    await started.wait()

    # Ensure MCP directory exists in sandbox
    await sandbox.exec(["mkdir", "-p", "/var/tmp/mcp"], timeout=30, concurrency=False)

    # Write MCP script to sandbox
    script_path = f"/var/tmp/mcp/{spec.name}_server.py"
    script = generate_mcp_server_script(spec.name, tools_info, instance)
    await sandbox.write_file(script_path, script)
    await anyio.sleep(1)

    return MCPServerConfigStdio(
        name=spec.name,
        command="python3",
        args=[script_path],
        tools="all",
    )
