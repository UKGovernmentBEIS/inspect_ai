from typing import Literal

from inspect_ai.tool._mcp._config import MCPServerConfigHTTP

from .._tool import Tool, ToolSource
from ._local import MCPServerLocal
from ._remote import MCPServerRemote, MCPServerTool
from ._types import MCPServer


def mcp_tools(
    server: MCPServer,
    *,
    tools: Literal["all"] | list[str] = "all",
) -> ToolSource:
    """Tools from MCP server.

    Args:
       server: MCP server created with `mcp_server_stdio()`, `mcp_server_http()`,
          or `mcp_server_sandbox()`.
       tools: List of tool names (or globs) (defaults to "all")
          which returns all tools.

    Returns:
       ToolSource: Source for specified MCP server tools.
    """
    if isinstance(server, MCPServerLocal):
        return MCPToolSourceLocal(server, tools)
    elif isinstance(server, MCPServerRemote):
        return MCPToolSourceRemote(server._config.model_copy(deep=True), tools)
    else:
        raise TypeError(f"Unexpected MCPServer type: {type(server)}")


class MCPToolSourceLocal(ToolSource):
    def __init__(
        self, server: MCPServerLocal, tools: Literal["all"] | list[str]
    ) -> None:
        self._server = server
        self._tools = tools
        self._cached_tool_list: list[Tool] | None = None

    async def tools(self) -> list[Tool]:
        if self._cached_tool_list is None:
            self._cached_tool_list = await self._server.tools(self._tools)
        return self._cached_tool_list


class MCPToolSourceRemote(ToolSource):
    def __init__(
        self, config: MCPServerConfigHTTP, tools: Literal["all"] | list[str]
    ) -> None:
        self._config = config
        self._tools = tools

    async def tools(self) -> list[Tool]:
        return [MCPServerTool(self._config, self._tools)]
