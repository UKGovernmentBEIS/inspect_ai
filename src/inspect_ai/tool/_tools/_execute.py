from inspect_ai.util import sandbox

from .._tool import Tool, tool
from .._tool_call import ToolCall, ToolCallContent, ToolCallView, ToolCallViewer


# custom viewer for bash and python code blocks
def code_viewer(language: str, code_param: str) -> ToolCallViewer:
    def viewer(tool_call: ToolCall) -> ToolCallView:
        code = tool_call.arguments.get(code_param, tool_call.function).strip()
        call = ToolCallContent(
            format="markdown",
            content=f"{language}\n\n```{language}\n" + code + "\n```\n",
        )
        return ToolCallView(call=call)

    return viewer


@tool(viewer=code_viewer("bash", "cmd"))
def bash(timeout: int | None = None, user: str | None = None) -> Tool:
    """Bash shell command execution tool.

    Execute bash shell commands using a sandbox environment (e.g. "docker").

    Args:
      timeout (int | None): Timeout (in seconds) for command.
      user (str | None): User to execute commands as.

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(cmd: str) -> str:
        """
        Use this function to execute bash commands.

        Args:
          cmd (str): The bash command to execute.

        Returns:
          The output of the command.
        """
        # execute the command
        result = await sandbox().exec(
            cmd=["bash", "-c", cmd], timeout=timeout, user=user
        )
        # return output (including stderr if any)
        output = ""
        if result.stderr:
            output = f"{result.stderr}\n"
        return f"{output}{result.stdout}"

    return execute


@tool(viewer=code_viewer("python", "code"))
def python(timeout: int | None = None, user: str | None = None) -> Tool:
    """Python code execution tool.

    Execute Python code using a sandbox environment (e.g. "docker").

    Args:
      timeout (int | None): Timeout (in seconds) for command.
      user (str | None): User to execute commands as.

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(code: str) -> str:
        """
        Use the python function to execute Python code.

        The python function will only return you the stdout of the script,
        oo make sure to use print to see the output.

        Args:
          code (str): The python code to execute.

        Returns:
          The output of the Python code.
        """
        result = await sandbox().exec(
            cmd=["python3"], input=code, timeout=timeout, user=user
        )
        # return output (including stderr if any)
        output = ""
        if result.stderr:
            output = f"{result.stderr}\n"
        return f"{output}{result.stdout}"

    return execute
