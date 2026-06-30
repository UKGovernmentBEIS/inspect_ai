from inspect_ai.util import sandbox as sandbox_env

from .._tool import Tool, tool
from .._tool_call import ToolCall, ToolCallContent, ToolCallView, ToolCallViewer
from .._tool_def import ToolDef


# custom viewer for bash and python code blocks
def code_viewer(
    language: str, code_param: str, title: str | None = None
) -> ToolCallViewer:
    title = title or language

    def viewer(tool_call: ToolCall) -> ToolCallView:
        code = tool_call.arguments.get(code_param, None)
        code = str(code or tool_call.function).strip()
        call = ToolCallContent(
            title=title,
            format="markdown",
            content=f"```{language}\n" + code + "\n```\n",
        )
        return ToolCallView(call=call)

    return viewer


# Background-task guidance appended to the model-facing description when
# bash(background=True). Kept free of any "sandbox"/evaluation framing so it
# does not cue the model that it is being evaluated.
_BASH_BACKGROUND_TIMEOUT = """\
Use this function to execute bash commands.

This tool terminates any command that runs longer than {timeout} seconds. For operations that may exceed this (builds, large downloads, model training, long-running servers), start them in the background and check on them in later calls instead of blocking. Launch the process and record its PID in the same call (`$!` is only valid in the call that launched it):

  nohup <command> > /tmp/task.log 2>&1 & echo "PID $!"

Each call runs in a fresh shell, but a background process keeps running between calls. Track the PID and log path yourself, then poll in later calls:

  ps -p <PID>                # still running?
  tail -n 50 /tmp/task.log   # latest output

Do not use `sleep` to wait for completion: a sleep longer than {timeout}s is itself terminated. Return and check again in a later call."""


_BASH_BACKGROUND_NO_TIMEOUT = """\
Use this function to execute bash commands.

For long-running operations (builds, large downloads, model training, long-running servers), consider starting them in the background so you can continue working and check on progress in later calls instead of blocking a single call. Launch the process and record its PID in the same call (`$!` is only valid in the call that launched it):

  nohup <command> > /tmp/task.log 2>&1 & echo "PID $!"

Each call runs in a fresh shell, but a background process keeps running between calls. Track the PID and log path yourself, then poll in later calls:

  ps -p <PID>                # still running?
  tail -n 50 /tmp/task.log   # latest output"""


def _bash_background_description(timeout: int | None) -> str:
    if timeout is not None:
        return _BASH_BACKGROUND_TIMEOUT.format(timeout=timeout)
    return _BASH_BACKGROUND_NO_TIMEOUT


@tool(viewer=code_viewer("bash", "command"), parallel=True)
def bash(
    timeout: int | None = None,
    user: str | None = None,
    sandbox: str | None = None,
    background: bool = False,
) -> Tool:
    """Bash shell command execution tool.

    Execute bash shell commands using a sandbox environment (e.g. "docker").

    Each call spawns a fresh subprocess and holds no per-call state, so
    multiple bash tool calls in the same assistant message run concurrently.
    The model is responsible for sequencing commands that depend on each
    other's filesystem side effects.

    Args:
      timeout: Timeout (in seconds) for command.
      user: User to execute commands as.
      sandbox: Optional sandbox environment name.
      background: Augment the tool description with guidance encouraging the
        model to run long-running commands detached (e.g. `nohup ... &`) and
        poll for progress in later calls rather than blocking. Off by default
        (the tool's behavior is unchanged; only the model-facing description
        is affected). When a `timeout` is set the guidance references it.

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(command: str) -> str:
        """
        Use this function to execute bash commands.

        Args:
          command: The bash command to execute.

        Returns:
          The output of the command.
        """
        # execute the command
        result = await sandbox_env(sandbox).exec(
            cmd=["bash", "--login", "-c", command], timeout=timeout, user=user
        )
        # return output (including stderr if any)
        output = ""
        if result.stderr:
            output = f"{result.stderr}\n"
        return f"{output}{result.stdout}"

    if not background:
        return execute

    return ToolDef(
        execute,
        name="bash",
        description=_bash_background_description(timeout),
        parameters={"command": "The bash command to execute."},
    ).as_tool()


@tool(viewer=code_viewer("python", "code"), parallel=True)
def python(
    timeout: int | None = None, user: str | None = None, sandbox: str | None = None
) -> Tool:
    """Python code execution tool.

    Execute Python code using a sandbox environment (e.g. "docker").

    Each call spawns a fresh subprocess and holds no per-call state, so
    multiple python tool calls in the same assistant message run concurrently.

    Args:
      timeout: Timeout (in seconds) for command.
      user: User to execute commands as.
      sandbox: Optional sandbox environment name.

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(code: str) -> str:
        """
        Use the python function to execute Python code.

        The Python tool executes single-run Python scripts. Important notes:
        1. Each execution is independent - no state is preserved between runs
        2. You must explicitly use print() statements to see any output
        3. Simply writing expressions (like in notebooks) will not display results
        4. The script cannot accept interactive input during execution
        5. Return statements alone won't produce visible output
        6. All variables and imports are cleared between executions
        7. Standard output (via print()) is the only way to see results

        Args:
          code (str): The python code to execute.

        Returns:
          The output of the Python code.
        """
        result = await sandbox_env(sandbox).exec(
            cmd=["bash", "--login", "-c", "python3 -"],
            input=code,
            timeout=timeout,
            user=user,
        )
        # return output (including stderr if any)
        output = ""
        if result.stderr:
            output = f"{result.stderr}\n"
        return f"{output}{result.stdout}"

    return execute
