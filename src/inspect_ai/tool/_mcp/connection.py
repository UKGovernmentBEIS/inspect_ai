import contextlib
from types import TracebackType
from typing import AsyncIterator, Sequence

from .._tool import Tool, ToolSource
from .._tool_def import ToolDef
from ._types import MCPServer
from .tools import MCPToolSource


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
        elif isinstance(tool_source, MCPToolSource):
            mcp_servers.append(tool_source._server)

    # enter connection contexts
    async with contextlib.AsyncExitStack() as exit_stack:
        for connection in [
            MCPServerConnection(mcp_server) for mcp_server in mcp_servers
        ]:
            await exit_stack.enter_async_context(connection)

        # onward
        yield


class MCPServerConnection:
    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def __aenter__(self) -> "MCPServerConnection":
        await self._server._connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._server._close()
