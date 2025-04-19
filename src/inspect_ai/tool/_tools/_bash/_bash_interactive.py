from pydantic import BaseModel, Field, RootModel
from shortuuid import uuid

from inspect_ai.tool import ToolResult
from inspect_ai.tool._tool_support_helpers import (
    exec_model_request,
    tool_container_sandbox,
)
from inspect_ai.util import StoreModel, store_as

from ..._tool import Tool, ToolParsingError, tool
from ..._tool_call import ToolCall, ToolCallContent, ToolCallView, ToolCallViewer


# These models are cloned from the container code. If/when we decide to create
# a package that is shared between the inspect and tool-container codebases, we'll
# just have to live with it.
class NewSessionResult(BaseModel):
    session_name: str


class BashRestartResult(BaseModel):
    pass


class BashCommandResult(BaseModel):
    status: int
    stdout: str
    stderr: str


class BashResult(RootModel[BashRestartResult | BashCommandResult]):
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


@tool(viewer=code_viewer("bash", "command"))
def bash_interactive(
    *,
    timeout: int | None = None,  # default timeout is 30 seconds
    idle_timeout: int | None = None,
    instance: str | None = uuid(),
) -> Tool:
    """Bash shell session command execution tool.

    Execute bash shell commands in a long running session using a sandbox environment (e.g. "docker").

    By default, a separate bash process is created within the sandbox for each
    call to `bash_session()`. You can modify this behavior by passing `instance=None`
    (which will result in a single bash process for the entire sample) or use other
    `instance` values that implement another scheme).

    See complete documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-bash-session>.

    Args:
      timeout: Timeout (in seconds) for command.
      instance: Instance id (each unique instance id has its own bash process)

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(
        input_text: str | None = None,
        restart: bool | None = None,
    ) -> ToolResult:
        r"""
        Interact with a bash shell.

        Supports interacting with the shell by sending input to it and retrieving
        output from it. The function waits until no additional output is sent to
        stdout or stderr for some idle period before returning any output.

        Example use case:
        - For a short-running shell command with a nominal amount of output, a
          single call to the function may suffice. e.g.
          ```
          bash_interactive(input_text="echo foo\n") -> "foo\n"
          ```
        - For a long-running command with output over time, multiple calls to the
          function are needed. e.g.
          ```
          bash_interactive(input_text="tail -f /tmp/foo.log\n") -> <some output>
          bash_interactive() -> <more output>
          # Send Ctrl+C (ETX character)
          bash_interactive(input_text="\u0003") -> "<final output>^C"
          ```
        - Interactive commands that may await more input from the user are also
          supported. e.g.
          ```
          bash_interactive(input_text="ssh fred@foo.com\n") -> "foo.com's password: "
          bash_interactive(input_text"secret\n") -> "fred@foo.com:~$ "
          ```

        Args:
          input_text: The input to send to the shell. If omitted, the function
                will return any additional content sent to the shell's stdout
                and stderr without sending new input.
          restart: Specifying true will restart this tool. Otherwise, leave this
                unspecified.

        Returns:
          The any output of the shell.
        """
        if not ((input_text is None) ^ (restart is None)):
            raise ToolParsingError(
                "Either 'input' or 'restart' must be specified, but not both."
            )

        sandbox = await tool_container_sandbox("bash interactive")
        store = store_as(BashSessionStore, instance=instance)

        if not store.session_id:
            store.session_id = (
                await exec_model_request(
                    sandbox,
                    "bash_interactive_new_session",
                    {},
                    NewSessionResult,
                    timeout,
                )
            ).session_name

        result = (
            await exec_model_request(
                sandbox,
                "bash_interactive",
                {
                    "session_name": store.session_id,
                    "input": input_text,
                    "restart": restart,
                },
                BashResult,
                timeout,
            )
        ).root

        if isinstance(result, BashRestartResult):
            return "Bash interactive restarted."

        # return output (including stderr if any)
        return f"{result.stderr}\n{result.stdout}" if result.stderr else result.stdout

    return execute
