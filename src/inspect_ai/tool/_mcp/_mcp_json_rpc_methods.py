from mcp import JSONRPCError, JSONRPCResponse

from ._mcp_controller import MCPController
from ._mcp_types import (
    KillServerParams,
    LaunchServerParams,
    SendNotificationParams,
    SendRequestParams,
)

controller = MCPController()


async def mcp_launch_server(**params: object) -> None:
    await controller.launch_server(LaunchServerParams.model_validate(params))


async def mcp_kill_server(**params: object) -> None:
    await controller.kill_server(KillServerParams.model_validate(params))


async def mcp_send_request(**params: object) -> JSONRPCResponse | JSONRPCError:
    return await controller.send_request(SendRequestParams.model_validate(params))


async def mcp_send_notification(**params: object) -> None:
    await controller.send_notification(SendNotificationParams.model_validate(params))
