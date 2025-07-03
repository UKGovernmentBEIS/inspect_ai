from ..._util.json_rpc_helpers import validated_json_rpc_method
from ._controller import Controller
from .tool_types import (
    BashParams,
    BashRestartResult,
    InteractParams,
    InteractResult,
    NewSessionParams,
    NewSessionResult,
    RestartParams,
)

controller = Controller()


@validated_json_rpc_method(NewSessionParams)
async def bash_session_new_session(params: NewSessionParams) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session(params.user))


@validated_json_rpc_method(BashParams)
async def bash_session(
    params: BashParams,
) -> InteractResult | BashRestartResult:
    match params.root:
        case InteractParams(
            session_name=session_name,
            input=input_text,
            wait_for_output=wait_for_output,
            idle_timeout=idle_timeout,
        ):
            return await controller.interact(
                session_name, input_text, wait_for_output, idle_timeout
            )
        case RestartParams(session_name=session_name):
            return await controller.restart(session_name)
