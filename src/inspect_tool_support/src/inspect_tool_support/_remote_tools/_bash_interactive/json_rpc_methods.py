from pydantic import BaseModel

from inspect_tool_support._remote_tools._bash_interactive.controller import (
    BashInteractiveController,
)
from inspect_tool_support._remote_tools._bash_interactive.tool_types import (
    BashInputResult,
    BashParams,
    BashRestartResult,
    InputParams,
    NewSessionResult,
    RestartParams,
)
from inspect_tool_support._util._json_rpc_helpers import validated_json_rpc_method

controller = BashInteractiveController()


# TODO: I need to refactor this code so that I can support no parameters. For now, we have a dummy model
class NoParams(BaseModel):
    pass


@validated_json_rpc_method(NoParams)
async def bash_interactive_new_session(params: NoParams) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session())


@validated_json_rpc_method(BashParams)
async def bash_interactive(params: BashParams) -> BashInputResult | BashRestartResult:
    match params.root:
        case InputParams(session_name=session_name, input=input):
            return await controller.execute_input(session_name, input)
        case RestartParams(session_name=session_name):
            return await controller.restart(session_name)
