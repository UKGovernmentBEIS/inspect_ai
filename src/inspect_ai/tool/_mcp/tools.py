from typing import Literal

from .._tool import Tool, ToolSource
from ._types import MCPServer


def mcp_tools(
    server: MCPServer,
    *,
    tools: Literal["all"] | list[str] = "all",
) -> ToolSource:
    """Tools from MCP server.

    Args:
       server: MCP server created with `mcp_server_stdio()` or `mcp_server_sse()`
       tools: List of tool names (or globs) (defaults to "all")
          which returns all tools.

    Returns:
       ToolSource: Source for specified MCP server tools.
    """
    return MCPToolSource(server, tools)


class MCPToolSource(ToolSource):
    def __init__(self, server: MCPServer, tools: Literal["all"] | list[str]) -> None:
        self._server = server
        self._tools = tools
        self._cached_tool_list: list[Tool] | None = None

    async def tools(self) -> list[Tool]:
        if self._cached_tool_list is None:
            self._cached_tool_list = await self._server._list_tools(self._tools)
        return self._cached_tool_list
