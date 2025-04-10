from itertools import count

from mcp import JSONRPCError, JSONRPCResponse

from ._mcp_server_session import MCPServerSession
from ._mcp_types import (
    KillServerParams,
    LaunchServerParams,
    SendNotificationParams,
    SendRequestParams,
)

sessions = dict[int, MCPServerSession]()
id_generator = count()


async def mcp_launch_server(**params: object) -> int:
    validated = LaunchServerParams.model_validate(params)
    session_id = next(id_generator)
    sessions[session_id] = await MCPServerSession.create(validated.server_params)
    return session_id


async def mcp_kill_server(**params: object) -> None:
    validated = KillServerParams.model_validate(params)
    session = sessions.pop(validated.session_id)
    # TODO: timeout
    timeout = 666
    await session.terminate(timeout=timeout)


async def mcp_send_request(**params: object) -> JSONRPCResponse | JSONRPCError:
    validated = SendRequestParams.model_validate(params)
    return await sessions[validated.session_id].send_request(validated.request)


async def mcp_send_notification(**params: object) -> None:
    validated = SendNotificationParams.model_validate(params)
    await sessions[validated.session_id].send_notification(validated.notification)
