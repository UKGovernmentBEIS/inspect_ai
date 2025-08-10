from types import TracebackType
from typing import Literal

from typing_extensions import override

from .._tool import Tool, ToolResult
from ._config import MCPConfig
from ._types import MCPServer

# https://platform.openai.com/docs/api-reference/responses/create#responses_create-tools
# https://docs.anthropic.com/en/api/messages#body-mcp-servers


class MCPServerRemote(MCPServer):
    def __init__(self, config: MCPConfig) -> None:
        self._config = config

    @override
    async def tools(self, tools: Literal["all"] | list[str] = "all") -> list[Tool]:
        return [MCPServerTool(self._config, tools)]

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


class MCPServerTool(Tool):
    def __init__(self, config: MCPConfig, tools: Literal["all"] | list[str]):
        self.config = config
        self.tools = tools

    @property
    def __name__(self) -> str:
        return f"mcp_server_{self.config.name}"

    async def __call__(self) -> ToolResult:
        raise RuntimeError("MCPServerTool should not be called directly")
