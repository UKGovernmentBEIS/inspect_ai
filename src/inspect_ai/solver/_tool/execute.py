from .environment import tool_environment
from .tool import Tool, tool


@tool(prompt="If you need to execute a bash command, use the bash tool.")
def bash() -> Tool:
    async def execute(cmd: str) -> str:
        """
        Execute a bash command.

        Args:
          cmd (str): The bash command to execute.

        Returns:
          The output of the command.
        """
        result = await tool_environment().exec(["bash", "-c", cmd])
        if result.success:
            return result.stdout
        else:
            return result.stderr

    return execute


@tool(prompt="If you need to execute python code, use the python tool.")
def python() -> Tool:
    async def execute(code: str) -> str:
        """
        Execute python code.

        Args:
          code (str): The python code to execute.

        Returns:
          The output of the command.
        """
        result = await tool_environment().exec(["python3"], input=code)
        if result.success:
            return result.stdout
        else:
            return result.stderr

    return execute
