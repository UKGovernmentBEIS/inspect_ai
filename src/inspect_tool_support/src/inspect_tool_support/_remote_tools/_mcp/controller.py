from mcp import JSONRPCRequest, StdioServerParameters

from inspect_tool_support._remote_tools._mcp.tool_types import (
    CreateProcessResult,
    ExecuteRequestResult,
    KillProcessResult,
)
from inspect_tool_support._util._session_controller import SessionController

from .mcp_session import McpSession

DEFAULT_SESSION_NAME = "McpSession"

# TODO: Sure would be cool if I had some sort of currying approach so that I
# avoid all of this boilerplate plumbing.


class McpSessionController(SessionController[McpSession]):
    """BashSessionController provides support for isolated inspect subtask sessions."""

    async def new_session(self) -> str:
        return await self.create_new_session(DEFAULT_SESSION_NAME, McpSession.create)

    async def create_process(
        self, session_name: str, server_name: str, server: StdioServerParameters
    ) -> CreateProcessResult:
        return await self.session_for_name(session_name).create_process(
            server_name, server
        )

    async def kill_process(
        self, session_name: str, server_name: str
    ) -> KillProcessResult:
        return await self.session_for_name(session_name).kill_process(server_name)

    async def execute_request(
        self,
        session_name: str,
        server_name: str,
        request: JSONRPCRequest,
        timeout: int = 30,
    ) -> ExecuteRequestResult:
        return await self.session_for_name(session_name).execute_request(
            server_name, request, timeout
        )
