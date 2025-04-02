import abc
from logging import getLogger
from types import TracebackType
from typing import Literal

from .._tool import Tool, ToolSource

logger = getLogger(__name__)


class MCPServer(ToolSource):
    """Model Context Protocol server interface."""

    async def __aenter__(self: "MCPServer") -> "MCPServer":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    @abc.abstractmethod
    async def list_tools(
        self, tools: Literal["all"] | list[str] = "all"
    ) -> list[Tool]: ...

    async def tools(self) -> list[Tool]:
        return await self.list_tools()
