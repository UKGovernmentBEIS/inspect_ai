from itertools import count

from jsonrpcserver import method
from mcp import JSONRPCError, JSONRPCResponse

from ..._util._json_rpc_helpers import with_validated_rpc_method_params
from .mcp_server_session import MCPServerSession
from .tool_types import (
    KillServerParams,
    LaunchServerParams,
    SendNotificationParams,
    SendRequestParams,
)

sessions = dict[int, MCPServerSession]()
id_generator = count()

# TODO: Check into with_validated_rpc_method_params's support of different
# return types such as `int` or `None`. You can see I'm returning `1` in a
# cases below


@method
async def mcp_launch_server(**params: object) -> object:
    return await with_validated_rpc_method_params(LaunchServerParams, _launch, **params)


@method
async def mcp_kill_server(**params: object) -> None:
    await with_validated_rpc_method_params(KillServerParams, _kill, **params)


@method
async def mcp_send_request(**params: object) -> object:
    return await with_validated_rpc_method_params(
        SendRequestParams, _send_request, **params
    )


@method
async def mcp_send_notification(**params: object) -> None:
    await with_validated_rpc_method_params(
        SendNotificationParams, _send_notification, **params
    )


async def _launch(params: LaunchServerParams) -> int:
    session_id = next(id_generator)
    sessions[session_id] = await MCPServerSession.create(params.server_params)
    return session_id


async def _kill(params: KillServerParams) -> int:
    session = sessions.pop(params.session_id)
    # TODO: timeout
    timeout = 666
    await session.terminate(timeout=timeout)
    return 1


async def _send_request(
    params: SendRequestParams,
) -> JSONRPCResponse | JSONRPCError:
    return await sessions[params.session_id].send_request(params.request)


async def _send_notification(params: SendNotificationParams) -> int:
    await sessions[params.session_id].send_notification(params.notification)
    return 1
