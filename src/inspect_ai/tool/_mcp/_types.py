import abc
from contextlib import AbstractAsyncContextManager
from logging import getLogger
from typing import Literal

from .._tool import Tool, ToolSource

logger = getLogger(__name__)


class MCPServer(ToolSource, AbstractAsyncContextManager["MCPServer"]):
    """Model Context Protocol server interface.

    `MCPServer` can be passed in the `tools` argument as a source of tools
    (use the `mcp_tools()` function to filter the list of tools)
    """

    @abc.abstractmethod
    async def tools(self, tools: Literal["all"] | list[str] = "all") -> list[Tool]:
        """List of all tools provided by this server.

        Args:
           tools: Either "all" for all tools or a list of globs for selected tools.
        """
        ...
