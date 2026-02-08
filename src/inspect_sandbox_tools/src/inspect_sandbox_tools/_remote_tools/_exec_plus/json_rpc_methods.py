from ..._util.json_rpc_helpers import validated_json_rpc_method
from ._controller import Controller
from .some_types import (
    ExecPlusPollRequest,
    ExecPlusPollResponse,
    ExecPlusStartRequest,
    ExecPlusStartResponse,
)

controller = Controller()


@validated_json_rpc_method(ExecPlusStartRequest)
async def exec_plus(params: ExecPlusStartRequest) -> ExecPlusStartResponse:
    session_name = await controller.new_session(
        cmd=params.cmd,
        env=params.env if params.env else None,
        cwd=params.cwd,
        initial_input=params.input,
    )

    return ExecPlusStartResponse(session_name=session_name)


@validated_json_rpc_method(ExecPlusPollRequest)
async def exec_plus_poll(params: ExecPlusPollRequest) -> ExecPlusPollResponse:
    return await controller.poll(
        session_name=params.session_name,
        wait_for_output=params.wait_for_output,
        idle_timeout=params.idle_timeout,
    )
