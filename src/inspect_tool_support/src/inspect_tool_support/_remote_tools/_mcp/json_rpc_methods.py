from jsonrpcserver import method
from pydantic import BaseModel

from inspect_tool_support._remote_tools._mcp.controller import McpSessionController
from inspect_tool_support._remote_tools._mcp.tool_types import (
    CreateProcessParams,
    CreateProcessResult,
    ExecuteRequestParams,
    ExecuteRequestResult,
    KillProcessParams,
    KillProcessResult,
    McpParams,
    NewSessionResult,
)
from inspect_tool_support._util._json_rpc_helpers import (
    with_validated_rpc_method_params,
)

controller = McpSessionController()


# TODO: I need to refactor this code so that I can support no parameters. For now, we have a dummy model
class NoParams(BaseModel):
    pass


@method
async def mcp_new_session() -> object:
    return await with_validated_rpc_method_params(NoParams, _mcp_new_session)


@method
async def mcp(**params: object) -> object:
    return await with_validated_rpc_method_params(McpParams, _mcp, **params)


async def _mcp_new_session(_: BaseModel) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session())


async def _mcp(
    params: McpParams,
) -> CreateProcessResult | KillProcessResult | ExecuteRequestResult:
    match params.root:
        case CreateProcessParams() as p:
            return await controller.create_process(
                p.session_name, p.server_name, p.server_params
            )
        case KillProcessParams() as p:
            return await controller.kill_process(p.session_name, p.server_name)
        case ExecuteRequestParams() as p:
            return await controller.execute_request(
                p.session_name, p.server_name, p.inner_request
            )
