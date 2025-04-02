from contextvars import ContextVar
from typing import Literal, cast

from .._tool import Tool, ToolSource
from ._types import MCPServer


def mcp_tools(
    server: MCPServer | str,
    tools: Literal["all"] | list[str] = "all",
) -> ToolSource:
    """Tools from MCP server.

    Args:
       server: MCP server (either explicitly created with `mcp_server_stdio()`
          or `mcp_server_sse()`, or a named MCP server specified in the `Task`
          `mcp_server` option.
       tools: List of tool names (or globs) (defaults to "all")
          which returns all tools.

    Returns:
       ToolSource: Source for specified MCP server tools.
    """
    return MCPToolSource(server, tools)


class MCPToolSource(ToolSource):
    def __init__(
        self, server: MCPServer | str, tools: Literal["all"] | list[str]
    ) -> None:
        self._server = server
        self._tools = tools
        self._cached_tool_list: list[Tool] | None = None

    async def tools(self) -> list[Tool]:
        # if it's a string, try to resolve to a server
        if isinstance(self._server, str):
            task_server = cast(
                MCPServer | None, _task_mcp_servers.get().get(self._server, None)
            )
            if task_server is None:
                raise RuntimeError(
                    f"MCP Server '{self._server}' not found (Did you specify it using `mcp_servers`? Is the name spelled correctly?)."
                )
            server = task_server
        else:
            server = self._server

        if self._cached_tool_list is None:
            self._cached_tool_list = await server.list_tools(self._tools)
        return self._cached_tool_list


def init_task_mcp_servers(mcp_servers: dict[str, MCPServer]) -> None:
    _task_mcp_servers.set(mcp_servers)


_task_mcp_servers: ContextVar[dict[str, MCPServer]] = ContextVar(
    "_task_mcp_servers", default={}
)
