import abc
from types import TracebackType


class McpServer(abc.ABC):
    def __init__(self) -> None:
        # state indicating whether our lifetime is bound by a context manager
        self._context_bound = False
        # have we been closed
        self._closed = False

    async def __aenter__(self: "McpServer") -> "McpServer":
        self._context_bound = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._closed:
            await self.close()
            self._closed = True

    @abc.abstractmethod
    async def close(self) -> None: ...


def mcp_server_remote() -> McpServer:
    return McpServerRemote()


def mcp_server_local() -> McpServer:
    return McpServerLocal()


def mcp_server_sandbox() -> McpServer:
    return McpServerSandbox()


class McpServerRemote(McpServer):
    def __init__(self) -> None:
        super().__init__()

    async def close(self) -> None:
        pass


class McpServerLocal(McpServer):
    def __init__(self) -> None:
        super().__init__()

    async def close(self) -> None:
        pass


class McpServerSandbox(McpServer):
    def __init__(self) -> None:
        super().__init__()

    async def close(self) -> None:
        pass
