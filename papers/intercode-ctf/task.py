from dataset import read_dataset

from inspect_ai import Task, task
from inspect_ai.scorer import includes
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
    system_message,
    tool,
    tool_environment,
    use_tools,
)


@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        plan=[
            system_message("system.txt"),
            use_tools([bash(), python()]),
            sample_setup(),
            generate(),
        ],
        scorer=includes(),
        max_messages=30,
        tool_environment="docker",
    )


@tool(prompt="If you need to execute a bash command, use the bash tool.")
def bash():
    async def execute(cmd: str):
        """
        Execute a bash command.

        Args:
          cmd (str): The bash command to execute.

        Returns:
          The output of the command.
        """
        result = await tool_environment().exec(cmd)
        if result.success:
            return result.stdout
        else:
            return result.stderr

    return execute


@tool(prompt="If you need to execute python code, use the python tool.")
def python():
    async def execute(code: str):
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


@solver
def sample_setup():
    """If the sample includes a setup command, execute that."""

    async def solve(state: TaskState, generate: Generate):
        if state.metadata.get("setup") is not None:
            await tool_environment().exec(state.metadata["setup"])
        return state

    return solve
