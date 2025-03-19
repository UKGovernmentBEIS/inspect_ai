from pydantic import BaseModel

from ..._util.json_rpc_helpers import validated_json_rpc_method
from ._controller import Controller
from .tool_types import (
    BashParams,
    BashRestartResult,
    InteractParams,
    InteractResult,
    NewSessionResult,
    RestartParams,
)

controller = Controller()


# TODO: I need to refactor this code so that I can support no parameters. For now, we have a dummy model
class NoParams(BaseModel):
    pass


@validated_json_rpc_method(NoParams)
async def bash_session_new_session(params: NoParams) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session())


@validated_json_rpc_method(BashParams)
async def bash_session(
    params: BashParams,
) -> InteractResult | BashRestartResult:
    match params.root:
        case InteractParams(
            session_name=session_name, input=input_text, wait_for_output=wait_for_output
        ):
            return await controller.interact(session_name, input_text, wait_for_output)
        case RestartParams(session_name=session_name):
            return await controller.restart(session_name)
