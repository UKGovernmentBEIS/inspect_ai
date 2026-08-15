import asyncio
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
retired_sessions: list[MCPServerSession] = []
id_generator = count()


@validated_json_rpc_method(LaunchServerParams)
async def mcp_launch_server(params: LaunchServerParams) -> int:
    session_id = next(id_generator)
    sessions[session_id] = await MCPServerSession.create(params.server_params)
    return session_id


@validated_json_rpc_method(KillServerParams)
async def mcp_kill_server(params: KillServerParams) -> None:
    # TODO: A later PR will audit/fix sandbox timeouts wholesale
    session = sessions.pop(params.session_id)
    try:
        await session.terminate(timeout=30)
    finally:
        retired_sessions.append(session)


async def shutdown() -> None:
    """Terminate every MCP session owned by this server."""
    active_sessions = [*sessions.values(), *retired_sessions]
    sessions.clear()
    retired_sessions.clear()
    results = await asyncio.gather(
        *(session.shutdown(timeout=30) for session in active_sessions),
        return_exceptions=True,
    )
    errors = [result for result in results if isinstance(result, Exception)]
    if errors:
        raise RuntimeError("; ".join(str(error) for error in errors))


@validated_json_rpc_method(SendRequestParams)
async def mcp_send_request(params: SendRequestParams) -> JSONRPCResponse | JSONRPCError:
    return await sessions[params.session_id].send_request(params.request)


@validated_json_rpc_method(SendNotificationParams)
async def mcp_send_notification(params: SendNotificationParams) -> None:
    await sessions[params.session_id].send_notification(params.notification)
