import contextlib
from typing import AsyncIterator, Sequence

from .._tool import Tool, ToolSource
from .._tool_def import ToolDef
from ._types import MCPServer
from .tools import MCPToolSourceLocal


@contextlib.asynccontextmanager
async def mcp_connection(
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
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
    tools = tools if isinstance(tools, Sequence) else [tools]
    tool_sources = [tool for tool in tools if isinstance(tool, ToolSource)]
    mcp_servers: list[MCPServer] = []
    for tool_source in tool_sources:
        if isinstance(tool_source, MCPServer):
            mcp_servers.append(tool_source)
        elif isinstance(tool_source, MCPToolSourceLocal):
            mcp_servers.append(tool_source._server)

    # enter connection contexts
    async with contextlib.AsyncExitStack() as exit_stack:
        for mcp_server in mcp_servers:
            await exit_stack.enter_async_context(mcp_server)

        # onward
        yield
