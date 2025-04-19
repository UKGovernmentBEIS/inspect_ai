from itertools import count

from mcp import JSONRPCError, JSONRPCResponse

from ..._util.json_rpc_helpers import validated_json_rpc_method
from .mcp_server_session import MCPServerSession
from .tool_types import (
    KillServerParams,
    LaunchServerParams,
    SendNotificationParams,
    SendRequestParams,
)

sessions = dict[int, MCPServerSession]()
id_generator = count()


@validated_json_rpc_method(LaunchServerParams)
async def mcp_launch_server(params: LaunchServerParams) -> int:
    session_id = next(id_generator)
    sessions[session_id] = await MCPServerSession.create(params.server_params)
    return session_id


@validated_json_rpc_method(KillServerParams)
async def mcp_kill_server(params: KillServerParams) -> None:
    # TODO: A later PR will audit/fix sandbox timeouts wholesale
    await sessions.pop(params.session_id).terminate(timeout=30)


@validated_json_rpc_method(SendRequestParams)
async def mcp_send_request(params: SendRequestParams) -> JSONRPCResponse | JSONRPCError:
    return await sessions[params.session_id].send_request(params.request)


@validated_json_rpc_method(SendNotificationParams)
async def mcp_send_notification(params: SendNotificationParams) -> None:
    await sessions[params.session_id].send_notification(params.notification)
