from mcp import JSONRPCError, JSONRPCRequest, JSONRPCResponse, StdioServerParameters
from mcp.types import JSONRPCNotification

from ._mcp_server_session import MCPServerSession
from ._mcp_types import (
    KillServerParams,
    LaunchServerParams,
    SendNotificationParams,
    SendRequestParams,
)


class MCPController:
    def __init__(self) -> None:
        self._sessions = dict[str, MCPServerSession]()

    # TODO: Let the controller define and return the session_id concept rather
    # than having the caller deal with it.
    async def launch_server(self, params: LaunchServerParams) -> None:
        self._sessions[params.session_id] = await MCPServerSession.create(
            params.server_params
        )

    async def kill_server(self, params: KillServerParams) -> None:
        # TODO: timeout
        timeout = 666
        # TODO: Refactor to share process management code from bash_session
        session = self._sessions.pop(params.session_id)
        await session.terminate(timeout=timeout)

    async def send_request(
        self, params: SendRequestParams
    ) -> JSONRPCResponse | JSONRPCError:
        return await self._sessions[params.session_id].send_request(params.request)

    async def send_notification(self, params: SendNotificationParams) -> None:
        return await self._sessions[params.session_id].send_notification(
            params.notification
        )
