from inspect_ai.util import sandbox

from .._tool import Tool, ToolError, tool


@tool(prompt="If you need to execute a bash command, use the bash tool.")
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
        Execute a bash command.

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


@tool(prompt="If you need to execute python code, use the python tool.")
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
        Execute python code.

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
