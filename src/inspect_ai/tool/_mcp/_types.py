import abc
from logging import getLogger
from types import TracebackType

logger = getLogger(__name__)


class McpClient(abc.ABC):
    """Model Context Protocol client interface."""

    def __init__(self) -> None:
        # state indicating whether our lifetime is bound by a context manager
        self._context_bound = False
        # have we been closed
        self._closed = False

    async def __aenter__(self: "McpClient") -> "McpClient":
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
                logger.warning(f"Unexpected error closing MCP client: {ex}")
            self._closed = True

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the client."""
        ...
