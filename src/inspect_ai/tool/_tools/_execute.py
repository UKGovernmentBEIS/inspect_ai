from inspect_ai.util import sandbox

from .._tool import Tool, ToolError, tool


@tool
def bash(timeout: int | None = None) -> Tool:
    """Bash shell command execution tool.

    Execute bash shell commands using a sandbox environment (e.g. "docker").

    Args:
      timeout (int | None): Timeout (in seconds) for command.

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
        result = await sandbox().exec(cmd=["bash", "-c", cmd], timeout=timeout)
        if result.success:
            return result.stdout
        else:
            raise ToolError(
                result.stderr if result.stderr else "error executing command"
            )

    return execute


@tool
def python(timeout: int | None = None) -> Tool:
    """Python code execution tool.

    Execute Python code using a sandbox environment (e.g. "docker").

    Args:
      timeout (int | None): Timeout (in seconds) for command.

    Returns:
      String with command output (stdout) or command error (stderr).
    """

    async def execute(code: str) -> str:
        """
        Use the python function to execute Python code.

        Args:
          code (str): The python code to execute.

        Returns:
          The output of the command.
        """
        result = await sandbox().exec(cmd=["python3"], input=code, timeout=timeout)
        if result.success:
            return result.stdout
        else:
            raise ToolError(result.stderr if result.stderr else "error executing code")

    return execute
