from inspect_ai.util import sandbox

from .._tool import Tool, tool
from .._tool_call import ToolCall, ToolCallContent, ToolCallView, ToolCallViewer


# custom viewer for bash and python code blocks
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
            cmd=["bash", "--login", "-c", cmd], timeout=timeout, user=user
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

        The Python tool executes single-run Python scripts. Important notes:
        1. Each execution is independent - no state is preserved between runs
        2. You must explicitly use print() statements to see any output
        3. Simply writing expressions (like in notebooks) will not display results
        4. The script cannot accept interactive input during execution
        5. Return statements alone won't produce visible output
        6. All variables and imports are cleared between executions
        7. Standard output (via print()) is the only way to see results

        Examples:
          INCORRECT (notebook style):
          x = 5
          x * 2           # Won't show anything
          return x * 2    # Won't show anything
          [1, 2, 3]       # Won't show anything

          CORRECT:
          x = 5
          print(x * 2)    # Will show: 10
          result = x * 2
          print(result)   # Will show: 10
          print([1, 2, 3])  # Will show: [1, 2, 3]

          INCORRECT (assuming previous imports persist):
          # First run:
          import numpy as np
          # Second run:
          arr = np.array([1, 2, 3])  # This will fail - numpy not imported in this run

          CORRECT (each run is self-contained):
          import numpy as np
          arr = np.array([1, 2, 3])
          print(arr)  # Will show: [1 2 3]

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
