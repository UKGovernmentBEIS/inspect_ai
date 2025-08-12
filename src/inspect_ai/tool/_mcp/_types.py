import abc
from contextlib import AbstractAsyncContextManager
from logging import getLogger

from .._tool import Tool, ToolSource

logger = getLogger(__name__)


class MCPServer(ToolSource, AbstractAsyncContextManager["MCPServer"]):
    """Model Context Protocol server interface.

    `MCPServer` can be passed in the `tools` argument as a source of tools
    (use the `mcp_tools()` function to filter the list of tools)
    """

    @abc.abstractmethod
    async def tools(self) -> list[Tool]:
        """List of all tools provided by this server"""
        ...
