from ..._util.json_rpc_helpers import validated_json_rpc_method
from ._controller import Controller
from .tool_types import (
    CloseStdinParams,
    CloseStdinResult,
    KillParams,
    KillResult,
    PollParams,
    PollResult,
    SubmitParams,
    SubmitResult,
    WriteStdinParams,
    WriteStdinResult,
)

controller = Controller()


@validated_json_rpc_method(SubmitParams)
async def exec_remote_start(params: SubmitParams) -> SubmitResult:
    """Submit a command for async execution. Returns the PID."""
    pid = await controller.submit(
        params.command,
        input=params.input,
        stdin_open=params.stdin_open,
        env=params.env,
        cwd=params.cwd,
    )
    return SubmitResult(pid=pid)


@validated_json_rpc_method(PollParams)
async def exec_remote_poll(params: PollParams) -> PollResult:
    """Poll job state and get incremental output."""
    return await controller.poll(params.pid)


@validated_json_rpc_method(KillParams)
async def exec_remote_kill(params: KillParams) -> KillResult:
    """Kill a running job."""
    return await controller.kill(params.pid)


@validated_json_rpc_method(WriteStdinParams)
async def exec_remote_write_stdin(params: WriteStdinParams) -> WriteStdinResult:
    """Write data to stdin of a running job."""
    return await controller.write_stdin(params.pid, params.data)


@validated_json_rpc_method(CloseStdinParams)
async def exec_remote_close_stdin(params: CloseStdinParams) -> CloseStdinResult:
    """Close stdin of a running job to signal EOF."""
    return await controller.close_stdin(params.pid)
