import contextlib
from copy import deepcopy
from typing import AsyncIterator, Sequence

from .._tool import Tool, ToolSource
from .._tool_def import ToolDef
from ._types import MCPServer
from .tools import MCPToolSource


@contextlib.asynccontextmanager
async def mcp_context(
    tools: Sequence[Tool | ToolDef | ToolSource],
) -> AsyncIterator[None]:
    """Context manager for running MCP servers required by tools.

    Any `ToolSource` passed in tools will be examined to see
    if it references an MCPServer, and if so, that server will be
    connected to upon entering the context and disconnected from
    upon exiting the context.

    Args:
       tools: Tools in current context.
    """
    # discover mcp servers in tools
    tool_sources = [tool for tool in tools if isinstance(tool, MCPToolSource)]
    mcp_servers: list[MCPServer] = []
    for tool_source in tool_sources:
        if isinstance(tool_source, MCPServer):
            mcp_servers.append(tool_source)
        elif isinstance(tool_source, MCPToolSource):
            mcp_servers.append(tool_source._server)

    # await them (deep copy so they retain isolated session state)
    async with contextlib.AsyncExitStack() as exit_stack:
        for mcp_server in deepcopy(mcp_servers):
            await exit_stack.enter_async_context(mcp_server)

        # onward
        yield
