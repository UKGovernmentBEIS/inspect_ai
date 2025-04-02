import abc
from logging import getLogger
from types import TracebackType

from inspect_ai.tool._tool import Tool

logger = getLogger(__name__)


class MCPServer(abc.ABC):
    """Model Context Protocol server interface."""

    def __init__(self) -> None:
        # state indicating whether our lifetime is bound by a context manager
        self._context_bound = False
        # have we been closed
        self._closed = False

    async def __aenter__(self: "MCPServer") -> "MCPServer":
        self._context_bound = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._closed:
            try:
                await self.close()
            except Exception as ex:
                logger.warning(f"Unexpected error closing MCP server: {ex}")
            self._closed = True

    @abc.abstractmethod
    async def initialize(self) -> None: ...

    @abc.abstractmethod
    async def list_tools(self) -> list[Tool]: ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the server interface."""
        ...
