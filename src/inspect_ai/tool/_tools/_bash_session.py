from pydantic import BaseModel, Field
from shortuuid import uuid

from inspect_ai.tool import ToolResult
from inspect_ai.util import StoreModel, store_as

from .._tool import Tool, ToolParsingError, tool
from .._tool_call import ToolCall, ToolCallContent, ToolCallView, ToolCallViewer
from .._tool_support_helpers import (
    exec_model_request,
    exec_scalar_request,
    tool_container_sandbox,
)

# These models are cloned from the container code. If/when we decide to create
# a package that is shared between the inspect and tool-container codebases, we'll
# just have to live with it.


class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class BashSessionStore(StoreModel):
    session_id: str = Field(default_factory=str)


# custom viewer for bash
def code_viewer(language: str, code_param: str) -> ToolCallViewer:
    def viewer(tool_call: ToolCall) -> ToolCallView:
        code = tool_call.arguments.get(code_param, None)
        code = (code or tool_call.function).strip()
        call = ToolCallContent(
            title=language,
            format="markdown",
            content=f"```{language}\n" + code + "\n```\n",
        )
        return ToolCallView(call=call)

    return viewer


DEFAULT_MAX_WAIT = 30
# this is how long we're willing to wait for the basic RPC call overhead.
TRANSPORT_TIMEOUT = 5


@tool(viewer=code_viewer("bash", "command"))
def bash_session(
    *,
    timeout: int | None = None,  # default is max_wait + 5 seconds
    wait_for_output: int | None = None,  # default is 30 seconds
    instance: str | None = uuid(),
) -> Tool:
    """Interactive bash shell session tool.

    Interact with a bash shell in a long running session using a sandbox
    environment (e.g. "docker"). This tool allows sending text to the shell,
    which could be a command followed by a newline character or any other input
    text such as the response to a password prompt.

    By default, a separate bash process is created within the sandbox for each
    call to `bash_session()`. You can modify this behavior by passing
    `instance=None` (which will result in a single bash process for the entire
    sample) or use other `instance` values that implement another scheme).

    See complete documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-bash-session>.

    Args:
      timeout: Timeout (in seconds) for command.
      wait_for_output: Maximum time (in seconds) to wait for output. If no
          output is received within this period, the function will return an
          empty string. The model may need to make multiple tool calls to obtain
          all output from a given command.
      instance: Instance id (each unique instance id has its own bash process)

    Returns:
      String with output from the shell.
    """
    wait_for_output = wait_for_output or DEFAULT_MAX_WAIT
    min_timeout = wait_for_output + TRANSPORT_TIMEOUT
    if timeout is None:
        timeout = min_timeout
    elif timeout < min_timeout:
        raise ValueError(
            f"Timeout must be at least {min_timeout} seconds, but got {timeout}."
        )

    async def execute(
        input: str | None = None,
        restart: bool | None = None,
    ) -> ToolResult:
        r"""
        Interact with a bash shell.

        Interact with a bash shell by sending it input text and retrieving output
        from it. There is no guarantee that all output will be returned in a
        single call. Call this function multiple times to retrieve additional
        output from the shell.

        IMPORTANT: You must include a trailing '\n' in your 'input_text' when
        appropriate. See the examples below for more details.

        Example use case:
        - For a short-running shell command with a nominal amount of output, a
          single call to the function may suffice. e.g.
          ```
          bash_session(input_text="echo foo\n") -> "foo\nuser@host:/# "
          ```
        - For a long-running command with output over time, multiple calls to the
          function are needed. e.g.
          ```
          bash_session(input_text="tail -f /tmp/foo.log\n") -> <some output>
          bash_session() -> <more output>
          # Send Ctrl+C (ETX character)
          bash_session(input_text="\u0003") -> "<final output>^Cuser@host:/# "
          ```
        - Interactive commands that may await more input from the user are also
          supported. e.g.
          ```
          bash_session(input_text="ssh fred@foo.com\n") -> "foo.com's password: "
          bash_session(input_text"secret\n") -> "fred@foo.com:~$ "
          ```

        Args:
          input: The input to send to the shell. If omitted, the function will
                return any additional content sent to the shell's stdout and
                stderr without sending new input.
          restart: Specifying true will restart this tool. Otherwise, leave this
                unspecified.

        Returns:
          The any output of the shell.
        """
        if restart and input is not None:
            raise ToolParsingError("Do not send any 'input_text' when restarting.")

        sandbox = await tool_container_sandbox("bash session")
        store = store_as(BashSessionStore, instance=instance)

        if not store.session_id:
            store.session_id = (
                await exec_model_request(
                    sandbox,
                    "bash_session_new_session",
                    {},
                    NewSessionResult,
                    TRANSPORT_TIMEOUT,
                )
            ).session_name

        if input and not input.endswith("\n"):
            # add a newline to the end of the input text
            input += "\n"

        result = await exec_scalar_request(
            sandbox,
            "bash_session",
            {
                "session_name": store.session_id,
                "wait_for_output": wait_for_output,
                "input": input,
                "restart": restart,
            },
            str,
            timeout,
        )

        if isinstance(result, BashRestartResult):
            return "Bash session restarted."

        # return output (including stderr if any)
        return result

    return execute
