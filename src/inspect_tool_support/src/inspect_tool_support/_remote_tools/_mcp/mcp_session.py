from asyncio.subprocess import Process

from mcp import JSONRPCRequest, JSONRPCResponse, StdioServerParameters

from inspect_tool_support._remote_tools._mcp.tool_types import (
    CreateProcessResult,
    KillProcessResult,
)


class McpSession:
    # TODO: Since there's nothing async in the create flow, it not longer needs to
    # be a class method. It can just be a normal constructor.
    @classmethod
    async def create(cls) -> "McpSession":
        return cls()

    def __init__(self) -> None:
        self._processes: dict[str, Process] = {}

    def _process_for_name(self, server_name: str) -> Process:
        return self._processes[server_name]

    async def create_process(
        self, server_name: str, server: StdioServerParameters
    ) -> CreateProcessResult:
        # TODO: Here's where I will call the MCP client code to create a process
        self._processes[server_name] = 666  # type: ignore
        return "OK"

    async def kill_process(self, server_name: str) -> KillProcessResult:
        # TODO: Here's where I will call the MCP client code to kill the process
        process = self._process_for_name(server_name)
        print(process)
        self._processes.pop(server_name)
        return "OK"

    async def execute_request(
        self, server_name: str, request: JSONRPCRequest, timeout: int = 30
    ) -> JSONRPCResponse:
        # TODO: Here's where we'll call the MCP client code to execute a command
        process = self._process_for_name(server_name)
        print(process)
        return {}  # type: ignore
