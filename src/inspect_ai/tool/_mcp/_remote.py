from types import TracebackType
from typing import Literal

from typing_extensions import override

from .._tool import Tool
from ._config import MCPConfig
from ._types import MCPServer


class MCPServerRemote(MCPServer):
    def __init__(self, config: MCPConfig) -> None:
        self._config = config

    @property
    def config(self) -> MCPConfig:
        """Configuration for remote server."""
        return self._config

    @override
    async def tools(self, tools: Literal["all"] | list[str] = "all") -> list[Tool]:
        # we are going to return a tool named "inspect_mcp_remote" and calling
        # that tool will yield an MCPConfig

        # we may be able to support dynamic binding if we can defer the server
        # connection until the first call to the server?
        return []

    # no-op async context manager as we don't manage resources
    @override
    async def __aenter__(self) -> MCPServer:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass
