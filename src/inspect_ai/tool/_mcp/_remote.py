from types import TracebackType

from typing_extensions import override

from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo

from .._tool import Tool, ToolResult
from ._config import MCPServerConfigHTTP
from ._types import MCPServer


class MCPServerRemote(MCPServer):
    def __init__(self, config: MCPServerConfigHTTP) -> None:
        self._config = config

    @override
    async def tools(self) -> list[Tool]:
        return [mcp_server_tool(self._config)]

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


def mcp_server_tool(config: MCPServerConfigHTTP) -> Tool:
    async def execute() -> ToolResult:
        raise RuntimeError("MCPServerTool should not be called directly")

    name = f"mcp_server_{config.name}"

    return ToolDef(
        execute,
        name=name,
        description=name,
        options=config.model_dump(),
    ).as_tool()


def is_mcp_server_tool(tool: ToolInfo) -> bool:
    return tool.name.startswith("mcp_server_") and tool.options is not None
