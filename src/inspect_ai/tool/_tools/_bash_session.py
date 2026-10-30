from typing import Annotated, Literal, NamedTuple
from weakref import WeakSet

import semver
from pydantic import BaseModel, Discriminator, Field, RootModel

from inspect_ai._util._json_rpc import (
    JSONRPCParamsType,
    exec_model_request,
    exec_scalar_request,
)
from inspect_ai.tool import ToolResult
from inspect_ai.tool._sandbox_tools_utils._error_mapper import (
    SandboxToolsErrorMapper,
)
from inspect_ai.tool._sandbox_tools_utils.sandbox import sandbox_with_injected_tools
from inspect_ai.util import StoreModel, store_as
from inspect_ai.util._sandbox._cli import SANDBOX_CLI, tools_user_param
from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.identity import (
    SandboxIdentityError,
    SandboxIdentityScope,
    sandbox_identity_scope,
    sandbox_identity_user,
)
from inspect_ai.util._sandbox.limits import SandboxEnvironmentLimits
from inspect_ai.util._tool_state import tool_state_instance

from .._tool import Tool, ToolError, ToolParsingError, tool

# These models are cloned from the container code. If/when we decide to create
# a package that is shared between the inspect and tool-container codebases, we'll
# just have to live with it.


class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class BashSessionStore(StoreModel):
    session_id: str = Field(default_factory=str)
    identity: str | None = Field(default=None)
    """User of the `sandbox_identity()` scope the session was created in."""
    identity_sandbox: str | None = Field(default=None)
    """Sandbox of the `sandbox_identity()` scope the session was created in."""


BOUND_SHELL_TOOLS_VERSION = semver.Version(1, 3, 0)
"""First inspect-sandbox-tools version with bound shells.

A shell created in a `sandbox_identity()` scope is bound to the scope's user: the
tools server gives it a name no other server issues and answers only requests that
name that user. A replaced server (or another sandbox) does not have the name, so a
saved scoped shell can never reach a shell another user opened under the same name.
"""

_bound_shell_sandboxes: WeakSet[SandboxEnvironment] = WeakSet()
"""Sandboxes whose tools were checked for `BOUND_SHELL_TOOLS_VERSION`."""


class _SessionNotFoundError(Exception):
    pass


class _BashSessionErrorMapper(SandboxToolsErrorMapper):
    @staticmethod
    def server_error(
        code: int, message: str, method: str, params: JSONRPCParamsType
    ) -> Exception:
        match code:
            case -32097:  # the server does not have the bound shell
                return _SessionNotFoundError(message)
            case -32096:  # the bound shell belongs to another user
                return SandboxIdentityError(message)
            case _:
                return SandboxToolsErrorMapper.server_error(
                    code, message, method, params
                )


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
TRANSPORT_TIMEOUT = 180  # Some K8's deployments can be very slow


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
      instance: Instance id (each unique instance id has its own bash process).
          Defaults to the current `tool_state_scope()`, if any.

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

        resolved_instance = tool_state_instance(instance)
        store = store_as(BashSessionStore, instance=resolved_instance)
        sandbox = await sandbox_with_injected_tools()
        session_user = sandbox_identity_user(sandbox, user, strict=True)
        scope = sandbox_identity_scope(sandbox)

        # Create transport for all RPC calls
        transport = SandboxJSONRPCTransport(sandbox, SANDBOX_CLI)

        if scope is not None or store.identity is not None:
            old_tools = await _tools_without_bound_shells(sandbox, transport)
            if old_tools is not None and scope is not None:
                raise SandboxIdentityError(
                    f"The sandbox has inspect-sandbox-tools {old_tools}, but "
                    "bash_session() in a sandbox identity scope needs version "
                    f"{BOUND_SHELL_TOOLS_VERSION} or later."
                )
            if old_tools is not None:
                raise ToolError(
                    "This sandbox's tools cannot use the saved shell. A new shell "
                    "can be started only inside the sandbox identity scope for "
                    f"'{store.identity}' in sandbox '{store.identity_sandbox}'."
                )

        async def new_session(replacing: str) -> _Session:
            """Open a shell and save it, unless another identity saved one first.

            `replacing` is the session the store held when this call read it.
            """
            params: dict[str, object] = {}
            if (run_as := tools_user_param(sandbox, session_user)) is not None:
                params["user"] = run_as
            if scope is not None:
                params["bind"] = True
            try:
                name = (
                    await exec_model_request(
                        method="bash_session_new_session",
                        params=params,
                        result_type=NewSessionResult,
                        transport=transport,
                        error_mapper=SandboxToolsErrorMapper,
                        timeout=TRANSPORT_TIMEOUT,
                        user=sandbox._tools_user,
                    )
                ).session_name
            except TimeoutError:
                raise RuntimeError("Timed out creating new session")
            session = _Session(
                name,
                scope.user if scope is not None else None,
                scope.sandbox if scope is not None else None,
            )
            # a concurrent call may have saved a shell during the request
            if store.session_id != replacing and (
                store.identity,
                store.identity_sandbox,
            ) != (session.owner, session.sandbox):
                raise _concurrent_session_error(resolved_instance, store, scope)
            store.session_id, store.identity, store.identity_sandbox = session
            return session

        # Choose the shell with no await after reading the store, and send to that
        # shell: a concurrent call can save another shell for this instance
        # meanwhile.
        if store.session_id:
            _check_shared_session(resolved_instance, store, scope)
            session = _Session(store.session_id, store.identity, store.identity_sandbox)
        else:
            session = await new_session("")

        timing: dict[str, object] = {
            "wait_for_output": wait_for_output,
            "idle_timeout": DEFAULT_IDLE_TIME,
            "max_output_bytes": SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE,
        }
        action_specific: dict[str, dict[str, object]] = {
            "type": {"input": input, **timing},
            # a bare type_submit is the return key alone, not the string "None"
            "type_submit": {
                "input": (input if input is not None else "") + "\n",
                **timing,
            },
            "interrupt": {"input": "\u0003", **timing},
            "read": timing,
            "restart": {"restart": True},
        }

        async def send(session: _Session) -> str:
            params: dict[str, object] = {"session_name": session.name}
            if session.owner is not None:
                params["owner"] = session.owner
            return await exec_scalar_request(
                method="bash_session",
                params={**params, **(action_specific[action])},
                result_type=str,
                transport=transport,
                error_mapper=_BashSessionErrorMapper,
                timeout=timeout,
                user=sandbox._tools_user,
            )

        try:
            result = await send(session)
        except _SessionNotFoundError:
            # A shell is bound only in its own scope, so this caller's scope (if
            # any) is the shell's, and a new shell opened here is bound the same.
            if action != "restart" or scope is None:
                raise _lost_session_error(resolved_instance, session, scope) from None
            # Recover once: a new shell lost before its first request is reported.
            session = await new_session(session.name)
            try:
                result = await send(session)
            except _SessionNotFoundError:
                raise _lost_session_error(resolved_instance, session, scope) from None

        # Return the appropriate response
        return (
            "Bash session restarted."
            if isinstance(result, BashRestartResult)
            else result
        )

    return execute


class _Session(NamedTuple):
    name: str
    owner: str | None
    """User of the scope the shell is bound to (None when unbound)."""
    sandbox: str | None
    """Sandbox of that scope."""


def _lost_session_error(
    instance: str | None, session: _Session, scope: SandboxIdentityScope | None
) -> ToolError:
    """The model-visible error for a bound shell the tools server no longer has.

    It is a tool error, not a `SandboxIdentityError`: the shell is the caller's
    own, and inside its scope the model recovers with the 'restart' action.
    """
    recovery = (
        "Use the 'restart' action to start a new shell."
        if scope is not None
        else "A new shell can be started only inside the sandbox identity scope "
        f"for '{session.owner}' in sandbox '{session.sandbox}'."
    )
    return ToolError(
        f"bash_session instance '{instance or 'default'}' was created as "
        f"'{session.owner}' in sandbox '{session.sandbox}', and the sandbox tools "
        "no longer have that shell: they were restarted, the sandbox was "
        f"restored, or this is another sandbox. {recovery}"
    )


async def _tools_without_bound_shells(
    sandbox: SandboxEnvironment, transport: SandboxJSONRPCTransport
) -> str | None:
    """The version of the sandbox's tools if they predate bound shells, else None.

    Older tools would give a scoped shell a counted name that a replaced server
    reissues to the next shell, whoever opens it.
    """
    if sandbox in _bound_shell_sandboxes:
        return None
    version = await exec_scalar_request(
        method="version",
        params={},
        result_type=str,
        transport=transport,
        error_mapper=SandboxToolsErrorMapper,
        timeout=TRANSPORT_TIMEOUT,
        user=sandbox._tools_user,
    )
    if semver.Version.parse(version) < BOUND_SHELL_TOOLS_VERSION:
        return version
    _bound_shell_sandboxes.add(sandbox)
    return None


def _check_shared_session(
    instance: str | None,
    store: BashSessionStore,
    scope: SandboxIdentityScope | None,
) -> None:
    """Refuse a saved shell created under another sandbox identity."""
    owner = _created_as(store)
    if scope is not None:
        if (store.identity, store.identity_sandbox) != (scope.user, scope.sandbox):
            raise SandboxIdentityError(
                f"bash_session instance '{instance or 'default'}' {owner}, so it "
                f"cannot be used inside the sandbox identity scope for "
                f"'{scope.user}' in sandbox '{scope.sandbox}'. A shell cannot be "
                "shared between sandbox identities."
            )


def _concurrent_session_error(
    instance: str | None,
    store: BashSessionStore,
    scope: SandboxIdentityScope | None,
) -> SandboxIdentityError:
    """Refuse a first call whose shell lost the race to another identity's."""
    caller = (
        f"inside the sandbox identity scope for '{scope.user}' in sandbox "
        f"'{scope.sandbox}'"
        if scope is not None
        else "outside a sandbox identity scope"
    )
    return SandboxIdentityError(
        f"bash_session instance '{instance or 'default'}' {_created_as(store)} by "
        f"a concurrent call, so it cannot be used {caller}. A shell cannot be "
        "shared between sandbox identities."
    )


def _created_as(store: BashSessionStore) -> str:
    return (
        f"was created as '{store.identity}' in sandbox '{store.identity_sandbox}'"
        if store.identity is not None
        else "was created outside a sandbox identity scope"
    )
