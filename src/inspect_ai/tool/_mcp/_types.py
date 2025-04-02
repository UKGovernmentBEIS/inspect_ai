import abc
from logging import getLogger
from types import TracebackType
from typing import Literal

from .._tool import Tool, ToolSource

logger = getLogger(__name__)


class MCPServer(ToolSource):
    """Model Context Protocol server interface.

    `MCPServer` can be passed in the `tools` argument as a source of tools
    (use the `mcp_tools()` function to filter the list of tools)

    """

    async def __aenter__(self: "MCPServer") -> "MCPServer":
        await self._connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._close()

    async def tools(self) -> list[Tool]:
        return await self._list_tools()

    @abc.abstractmethod
    async def _connect(self) -> None: ...

    @abc.abstractmethod
    async def _close(self) -> None: ...

    @abc.abstractmethod
    async def _list_tools(
        self, tools: Literal["all"] | list[str] = "all"
    ) -> list[Tool]: ...
