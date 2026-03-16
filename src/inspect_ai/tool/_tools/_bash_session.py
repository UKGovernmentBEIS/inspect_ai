from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, Field, RootModel

from inspect_ai._util._json_rpc import exec_model_request, exec_scalar_request
from inspect_ai.tool import ToolResult
from inspect_ai.tool._sandbox_tools_utils._error_mapper import (
    SandboxToolsErrorMapper,
)
from inspect_ai.tool._sandbox_tools_utils.sandbox import sandbox_with_injected_tools
from inspect_ai.util import StoreModel, store_as
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from .._tool import Tool, ToolParsingError, tool

# These models are cloned from the container code. If/when we decide to create
# a package that is shared between the inspect and tool-container codebases, we'll
# just have to live with it.


class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class BashSessionStore(StoreModel):
    session_id: str = Field(default_factory=str)
    sandbox: SandboxEnvironment | None = Field(default=None)


# Action-specific parameter models


class TypeParams(BaseModel):
    action: Literal["type"] = "type"
    input: str


class TypeSubmitParams(BaseModel):
    action: Literal["type_submit"] = "type_submit"
    input: str


class RestartParams(BaseModel):
    action: Literal["restart"] = "restart"


class ReadParams(BaseModel):
    action: Literal["read"] = "read"


class InterruptParams(BaseModel):
    action: Literal["interrupt"] = "interrupt"


class BashSessionParams(
    RootModel[
        TypeParams | TypeSubmitParams | RestartParams | ReadParams | InterruptParams
    ]
):
    root: Annotated[
        TypeParams | TypeSubmitParams | RestartParams | ReadParams | InterruptParams,
        Discriminator("action"),
    ]


DEFAULT_WAIT_FOR_OUTPUT = 30
DEFAULT_IDLE_TIME = 0.5
# this is how long we're willing to wait for the basic RPC call overhead.
TRANSPORT_TIMEOUT = 30  # Some K8's deployments can be very slow


@tool()
def bash_session(
    *,
    timeout: int | None = None,  # default is max_wait + 5 seconds
    wait_for_output: int | None = None,  # default is 30 seconds
    user: str | None = None,
    instance: str | None = None,
) -> Tool:
    """Interactive bash shell session tool.

    Interact with a bash shell in a long running session using a sandbox
    environment (e.g. "docker"). This tool allows sending text to the shell,
    which could be a command followed by a newline character or any other input
    text such as the response to a password prompt.

    To create a separate bash process for each
    call to `bash_session()`, pass a unique value for `instance`

    See complete documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-bash-session>.

    Args:
      timeout: Timeout (in seconds) for command.
      wait_for_output: Maximum time (in seconds) to wait for output. If no
          output is received within this period, the function will return an
          empty string. The model may need to make multiple tool calls to obtain
          all output from a given command.
      user: Username to run commands as
      instance: Instance id (each unique instance id has its own bash process)

    Returns:
      String with output from the shell.
    """
    wait_for_output = wait_for_output or DEFAULT_WAIT_FOR_OUTPUT
    min_timeout = wait_for_output + TRANSPORT_TIMEOUT
    if timeout is None:
        timeout = min_timeout
    elif timeout < min_timeout:
        raise ValueError(
            f"Timeout must be at least {min_timeout} seconds, but got {timeout}."
        )

    async def execute(
        action: Literal["type", "type_submit", "restart", "read", "interrupt"],
        input: str | None = None,
    ) -> ToolResult:
        r"""
        Interact with a bash shell.

        Interact with a bash shell by sending it input text and retrieving output
        from it. There is no guarantee that all output will be returned in a
        single call. Call this function multiple times to retrieve additional
        output from the shell.

        USAGE NOTES:
        - Ensure that the shell is at a command prompt (typically when the
          output ends in "$ " or "# ") before submitting a new command.
        - Control characters must be sent as Unicode escape sequences (e.g., use
          "\u0003" for Ctrl+C/ETX, "\u0004" for Ctrl+D/EOT). The literal string
          "Ctrl+C" will not be interpreted as a control character.
        - Use the "read" action to retrieve output from the shell without
          sending any input. This is useful for long-running commands that
          produce output over time. The "read" action will return any new output
          since the last call.
        - If a long-running command is in progress, additional input to execute
          a new command will not be processed until the previous completes. To
          abort a long-running command, use the "interrupt" action:
          `bash_session(action="interrupt")`
        - If output ends with "> " (the shell's continuation prompt), it means
          the previous input contained unmatched quotes, backticks, or other
          incomplete syntax. Either complete the quoted input or use the
          "interrupt" action to cancel, then retry with corrected input.

        Example use case:
        - For a short-running command with a nominal amount of output, a single
          call may suffice.
          ```
          bash_session(action="type_submit", input="echo foo") -> "foo\nuser@host:/# "
          ```
        - For a long-running command with output over time, multiple calls to are needed.
          ```
          bash_session(action="type_submit", input="tail -f /tmp/foo.log") -> <some output>
          bash_session(action="read") -> <more output>
          # Send interrupt (Ctrl+C)
          bash_session(action="interrupt") -> "<final output>^Cuser@host:/# "
          ```
        - Interactive command awaiting more input from the user.
          ```
          bash_session(action="type_submit", input="ssh fred@foo.com") -> "foo.com's password: "
          bash_session(action="type_submit", input="secret") -> "fred@foo.com:~$ "
          ```

        Args:
          action: The action to execute:
                - "type": Send input without a return key
                - "type_submit": Send input followed by a return key
                - "read": Read any new output without sending input
                - "interrupt": Send a Ctrl+C (ETX character) to interrupt the current process
                - "restart": Restart the bash session
          input: The input to send to the shell.
                Required for "type". Optional for "type_submit" actions. Must
                not be provided for "restart", "read", or "interrupt" actions.

        Returns:
          The accumulated output of the shell.
        """
        # Validate parameters based on action
        match action:
            case "type":
                if input is None:
                    raise ToolParsingError(
                        f"'input' is required for '{action}' action."
                    )
            case "restart" | "read" | "interrupt":
                if input is not None:
                    raise ToolParsingError(
                        f"Do not provide 'input' with '{action}' action."
                    )

        store = store_as(BashSessionStore, instance=instance)
        sandbox = await _get_sandbox(store)

        # Create transport for all RPC calls
        transport = SandboxJSONRPCTransport(sandbox, SANDBOX_CLI)

        if not store.session_id:
            try:
                store.session_id = (
                    await exec_model_request(
                        method="bash_session_new_session",
                        params={},
                        result_type=NewSessionResult,
                        transport=transport,
                        error_mapper=SandboxToolsErrorMapper,
                        timeout=TRANSPORT_TIMEOUT,
                        user=user,
                    )
                ).session_name
            except TimeoutError:
                raise RuntimeError("Timed out creating new session")

        timing: dict[str, object] = {
            "wait_for_output": wait_for_output,
            "idle_timeout": DEFAULT_IDLE_TIME,
        }
        action_specific: dict[str, dict[str, object]] = {
            "type": {"input": input, **timing},
            "type_submit": {"input": f"{input}\n", **timing},
            "interrupt": {"input": "\u0003", **timing},
            "read": timing,
            "restart": {"restart": True},
        }

        result = await exec_scalar_request(
            method="bash_session",
            params={"session_name": store.session_id, **(action_specific[action])},
            result_type=str,
            transport=transport,
            error_mapper=SandboxToolsErrorMapper,
            timeout=timeout,
            user=user,
        )

        # Return the appropriate response
        return (
            "Bash session restarted."
            if isinstance(result, BashRestartResult)
            else result
        )

    return execute


async def _get_sandbox(store: BashSessionStore) -> SandboxEnvironment:
    if not store.sandbox:
        store.sandbox = await sandbox_with_injected_tools()

    return store.sandbox
