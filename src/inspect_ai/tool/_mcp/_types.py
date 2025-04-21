import abc
from logging import getLogger
from typing import Literal

from .._tool import Tool, ToolSource

logger = getLogger(__name__)


class MCPServer(ToolSource):
    """Model Context Protocol server interface.

    `MCPServer` can be passed in the `tools` argument as a source of tools
    (use the `mcp_tools()` function to filter the list of tools)

    """

    async def tools(self) -> list[Tool]:
        """List of all tools provided by this server."""
        return await self._list_tools()

    @abc.abstractmethod
    async def _connect(self) -> None: ...

    @abc.abstractmethod
    async def _close(self) -> None: ...

    @abc.abstractmethod
    async def _list_tools(
        self, tools: Literal["all"] | list[str] = "all"
    ) -> list[Tool]: ...
