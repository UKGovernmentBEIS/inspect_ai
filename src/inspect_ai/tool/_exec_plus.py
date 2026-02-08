from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from inspect_ai.tool._json_rpc_helpers import (
    exec_model_request,
)
from inspect_ai.tool._sandbox_tools_utils._runtime_helpers import (
    SandboxJSONRPCTransport,
    SandboxToolsServerErrorMapper,
)

if TYPE_CHECKING:
    from inspect_ai.util._sandbox.environment import SandboxEnvironment

from inspect_ai.tool._sandbox_tools_utils.sandbox import SANDBOX_TOOLS_CLI
from inspect_ai.util._subprocess import ExecResult

# Similar to _bash_session, these are copied from the container code


class ExecPlusStartRequest(BaseModel):
    cmd: list[str]
    input: str | bytes | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class ExecPlusStartResponse(BaseModel):
    session_name: str


class ExecPlusPollRequest(BaseModel):
    session_name: str
    wait_for_output: int = 30
    idle_timeout: float = 0.5


class ExecPlusPollResponse(BaseModel):
    stdout: str
    stderr: str
    completed: bool = False
    exit_code: int | None = None


async def exec_plus_start(
    sandbox: SandboxEnvironment,
    cmd: list[str],
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] = {},
    user: str | None = None,
    timeout: int | None = None,
    timeout_retry: bool = True,
    concurrency: bool = True,
) -> ExecPlusStartResponse:
    """Start a command in a sandbox with enhanced session management.

    Args:
        sandbox: The sandbox environment to execute the command in.
        cmd: Command or command and arguments to execute.
        input: Standard input (optional).
        cwd: Current working directory (optional).
        env: Environment variables for execution.
        user: Optional username or UID to run the command as.
        timeout: Optional execution timeout (seconds).
        timeout_retry: Retry the command in the case that it times out.
        concurrency: Request throttling of concurrent subprocesses.

    Returns:
        Response containing the session name.
    """
    transport = SandboxJSONRPCTransport(sandbox, SANDBOX_TOOLS_CLI)
    server_error_mapper = SandboxToolsServerErrorMapper()

    exec_plus_start_response: ExecPlusStartResponse = await exec_model_request(
        method="exec_plus",
        params=ExecPlusStartRequest(
            cmd=cmd,
            input=input,
            cwd=cwd,
            env=env,
            # user=user,
            # timeout=timeout,
            # timeout_retry=timeout_retry,
        ).model_dump(),
        result_type=ExecPlusStartResponse,
        transport=transport,
        server_error_mapper=server_error_mapper,
        timeout=10,
        user=user,
    )
    return exec_plus_start_response


async def exec_plus_poll(
    sandbox: SandboxEnvironment,
    session_name: str,
    user: str | None = None,
) -> ExecPlusPollResponse:
    """Poll a running command for output.

    Args:
        sandbox: The sandbox environment to execute the command in.
        session_name: The session name of the command to poll.
        user: Optional username or UID to run the command as.

    Returns:
        Response containing stdout, stderr, and completion status.
    """
    transport = SandboxJSONRPCTransport(sandbox, SANDBOX_TOOLS_CLI)
    server_error_mapper = SandboxToolsServerErrorMapper()

    return await exec_model_request(
        method="exec_plus_poll",
        params=ExecPlusPollRequest(session_name=session_name).model_dump(),
        result_type=ExecPlusPollResponse,
        transport=transport,
        server_error_mapper=server_error_mapper,
        user=user,
    )
