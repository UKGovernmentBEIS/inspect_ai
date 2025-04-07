import abc
from contextlib import _AsyncGeneratorContextManager
from logging import getLogger
from types import TracebackType
from typing import AsyncGenerator, Literal, TypeAlias

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.types import JSONRPCMessage

from .._tool import Tool, ToolSource

logger = getLogger(__name__)


MCPServerContext: TypeAlias = _AsyncGeneratorContextManager[
    tuple[
        MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        MemoryObjectSendStream[JSONRPCMessage],
    ]
]

# TODO: Figure out if I can/should update MCPServerContext to be this
MCPServerContextEric: TypeAlias = AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        MemoryObjectSendStream[JSONRPCMessage],
    ],
]


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
