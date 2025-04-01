from contextlib import AsyncExitStack, _AsyncGeneratorContextManager
from pathlib import Path
from typing import Any, Literal, TypeAlias

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import Tool
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import JSONRPCMessage

from ._types import McpClient

McpClientContext: TypeAlias = _AsyncGeneratorContextManager[
    tuple[
        MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        MemoryObjectSendStream[JSONRPCMessage],
    ]
]


class McpClientImpl(McpClient):
    def __init__(
        self,
        client: McpClientContext,
    ) -> None:
        super().__init__()
        self._client = client
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Attempted to access session before it is initialized")
        return self._session

    async def initialize(self) -> None:
        await self._ensure_session()

    async def list_tools(self) -> list[Tool]:
        await self._ensure_session()
        return (await self.session.list_tools()).tools

    async def close(self) -> None:
        await self._exit_stack.aclose()

    async def _ensure_session(self) -> None:
        if self._session is None:
            streams = await self._exit_stack.enter_async_context(self._client)
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(*streams)
            )
            await self._session.initialize()


def create_sse_client(
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> McpClient:
    return McpClientImpl(sse_client(url, headers, timeout, sse_read_timeout))


def create_stdio_client(
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    encoding: str = "utf-8",
    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
) -> McpClient:
    return McpClientImpl(
        stdio_client(
            StdioServerParameters(
                command=command,
                args=args,
                cwd=cwd,
                env=env,
                encoding=encoding,
                encoding_error_handler=encoding_error_handler,
            )
        )
    )
