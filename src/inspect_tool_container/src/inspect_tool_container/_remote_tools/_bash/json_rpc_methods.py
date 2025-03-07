import jsonrpcserver

from inspect_tool_container._remote_tools._bash.controller import Controller
from inspect_tool_container._remote_tools._bash.tool_types import (
    BashCommandResult,
    BashParams,
    BashRestartResult,
    CommandParams,
    RestartParams,
)
from inspect_tool_container._util._json_rpc_helpers import (
    with_validated_rpc_method_params,
)

controller = Controller()


@jsonrpcserver.method
async def bash(**params: object) -> object:
    return await with_validated_rpc_method_params(BashParams, _bash, **params)


async def _bash(params: BashParams) -> BashCommandResult | BashRestartResult:
    match params.root:
        case CommandParams(command=command):
            return await controller.execute_command(command)
        case RestartParams():
            return await controller.restart()
