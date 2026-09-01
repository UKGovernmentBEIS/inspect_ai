from fnmatch import fnmatch
from typing import Literal

from inspect_ai.tool._tool_def import ToolDef

from .._tool import Tool, ToolSource
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
    from ._local import MCPServerLocal
    from ._remote import MCPServerRemote

    if isinstance(server, MCPServerLocal):
        return MCPToolSourceLocal(server, tools)
    elif isinstance(server, MCPServerRemote):
        return MCPServerRemote(
            server._config.model_copy(update={"tools": tools}, deep=True)
        )
    else:
        raise TypeError(f"Unexpected MCPServer type: {type(server)}")


class MCPToolSourceLocal(ToolSource):
    def __init__(self, server: MCPServer, tools: Literal["all"] | list[str]) -> None:
        self._server = server
        self._tools = tools

    async def tools(self) -> list[Tool]:
        # Every Tool returned by the server closes over the MCPServerLocalSession
        # that produced it, and those sessions are scoped per async task (see
        # MCPServerLocal._task_session). A ToolSource, by contrast, is shared:
        # inspect eval builds one per Task and every sample uses it. An
        # uncached call here still costs no extra transport round trip: the
        # session itself caches the raw tool list per scope (see
        # MCPServerLocalSession.tools), so re-resolving on every call only
        # repeats the fnmatch filtering and ToolDef wrapping, not the server
        # round trip.
        mcp_tools = await self._server.tools()

        # filter them
        def include_tool(tool: Tool) -> bool:
            if self._tools == "all":
                return True
            else:
                return any([fnmatch(ToolDef(tool).name, t) for t in self._tools])

        return [mcp_tool for mcp_tool in mcp_tools if include_tool(mcp_tool)]
