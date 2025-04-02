import abc
from logging import getLogger
from types import TracebackType
from typing import Literal

from inspect_ai.tool._tool import Tool

logger = getLogger(__name__)


class MCPServer:
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
