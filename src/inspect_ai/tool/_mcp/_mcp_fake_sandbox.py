from typing import Type, TypeVar

from pydantic import BaseModel

from ._mcp_json_rpc_methods import (
    mcp_kill_server,
    mcp_launch_server,
    mcp_send_notification,
    mcp_send_request,
)

StrIntOrModelT = TypeVar("StrIntOrModelT", bound=str | int | BaseModel)


class FakeSandbox:
    pass


async def exec_sandbox_rpc(
    sandbox: FakeSandbox,
    method: str,
    params: dict[str, object] | tuple[object, ...],
    result_cls: Type[StrIntOrModelT],
    timeout: int | None = None,
) -> StrIntOrModelT:
    assert isinstance(params, dict)
    match method:
        case "mcp_launch_server":
            return await mcp_launch_server(**params)
        case "mcp_kill_server":
            return await mcp_kill_server(**params)
        case "mcp_send_request":
            # TODO: Make sure that validation exceptions thrown here are plumbed
            # properly
            return await mcp_send_request(**params)
        case "mcp_send_notification":
            return await mcp_send_notification(**params)
        case _:
            assert False
