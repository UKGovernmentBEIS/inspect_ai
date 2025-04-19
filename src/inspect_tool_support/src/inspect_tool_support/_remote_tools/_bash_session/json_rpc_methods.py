from pydantic import BaseModel

from inspect_tool_support._remote_tools._bash_session.controller import (
    BashSessionController,
)
from inspect_tool_support._remote_tools._bash_session.tool_types import (
    BashCommandResult,
    BashParams,
    BashRestartResult,
    CommandParams,
    NewSessionResult,
    RestartParams,
)
from inspect_tool_support._util._json_rpc_helpers import validated_json_rpc_method

controller = BashSessionController()


# TODO: I need to refactor this code so that I can support no parameters. For now, we have a dummy model
class NoParams(BaseModel):
    pass


@validated_json_rpc_method(NoParams)
async def bash_session_new_session(params: NoParams) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session())


@validated_json_rpc_method(BashParams)
async def bash_session(params: BashParams) -> BashCommandResult | BashRestartResult:
    match params.root:
        case CommandParams(session_name=session_name, command=command):
            return await controller.execute_command(session_name, command)
        case RestartParams(session_name=session_name):
            return await controller.restart(session_name)
