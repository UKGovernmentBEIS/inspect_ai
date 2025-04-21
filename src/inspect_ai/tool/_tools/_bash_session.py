from pydantic import BaseModel, Field, RootModel
from shortuuid import uuid

from inspect_ai.tool import ToolResult
from inspect_ai.tool._tool_support_helpers import (
    exec_model_request,
    tool_container_sandbox,
)
from inspect_ai.util import StoreModel, store_as

from .._tool import Tool, ToolParsingError, tool
from .._tool_call import ToolCall, ToolCallContent, ToolCallView, ToolCallViewer


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
def bash_session(*, timeout: int | None = None, instance: str | None = uuid()) -> Tool:
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
        command: str | None = None,
        restart: bool | None = None,
    ) -> ToolResult:
        """
        Use this function to execute bash commands.

        Args:
          command: The bash command to run. Required unless the tool is being restarted.
          restart: Specifying true will restart this tool. Otherwise, leave this unspecified.

        Returns:
          The output of the command.
        """
        if not ((command is None) ^ (restart is None)):
            raise ToolParsingError(
                "Either 'command' or 'restart' must be specified, but not both."
            )
        params: dict[str, object] = {"command": command, "restart": restart}

        sandbox = await tool_container_sandbox("bash session")
        store = store_as(BashSessionStore, instance=instance)

        if not store.session_id:
            store.session_id = (
                await exec_model_request(
                    sandbox=sandbox,
                    method="bash_session_new_session",
                    params={},
                    result_type=NewSessionResult,
                    timeout=timeout,
                )
            ).session_name

        params["session_name"] = store.session_id

        result = (
            await exec_model_request(
                sandbox=sandbox,
                method="bash_session",
                params=params,
                result_type=BashResult,
                timeout=timeout,
            )
        ).root

        if isinstance(result, BashRestartResult):
            return "Bash session restarted."

        # return output (including stderr if any)
        return f"{result.stderr}\n{result.stdout}" if result.stderr else result.stdout

    return execute
