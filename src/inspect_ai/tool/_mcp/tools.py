from fnmatch import fnmatch
from typing import Literal, Protocol, runtime_checkable

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


@runtime_checkable
class _ToolCacheScopeProvider(Protocol):
    def _tool_cache_scope(self) -> object: ...


def _tool_cache_scope(server: MCPServer) -> object:
    if isinstance(server, _ToolCacheScopeProvider):
        return server._tool_cache_scope()
    return server


class MCPToolSourceLocal(ToolSource):
    def __init__(self, server: MCPServer, tools: Literal["all"] | list[str]) -> None:
        self._server = server
        self._tools = tools
        self._cached_tool_list: list[Tool] | None = None
        self._cached_tool_scope: object | None = None

    async def tools(self) -> list[Tool]:
        # Every Tool returned by the server closes over the MCPServerLocalSession
        # that produced it, and those sessions are scoped per async task (see
        # MCPServerLocal._task_session). A ToolSource, by contrast, is shared:
        # inspect eval builds one per Task and every sample uses it. Caching the
        # resolved list on the instance therefore handed later samples tools
        # bound to the FIRST sample's session, so their tool calls executed in
        # that sample's sandbox while their own sandbox was never touched.
        #
        # Re-resolve when the scope changes, so a cached list can never outlive
        # the session it is bound to. The scope token is the per-task session
        # OBJECT (not the raw task id): asyncio task ids are id()-based and can
        # be reused once an earlier task is collected, so two tasks can share
        # an id over time while their sessions remain distinct. The attribute
        # name is retained because callers clear it to force a refetch after
        # tool visibility changes.
        scope = _tool_cache_scope(self._server)
        if self._cached_tool_list is None or self._cached_tool_scope is not scope:
            # get the underlying tools
            mcp_tools = await self._server.tools()

            # filter them
            def include_tool(tool: Tool) -> bool:
                if self._tools == "all":
                    return True
                else:
                    return any([fnmatch(ToolDef(tool).name, t) for t in self._tools])

            self._cached_tool_list = [
                mcp_tool for mcp_tool in mcp_tools if include_tool(mcp_tool)
            ]
            self._cached_tool_scope = scope
        return self._cached_tool_list
