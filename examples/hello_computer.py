from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool


@tool
def computer():
    async def execute(
        action: str,
        text: str | None = None,
        coordinate: list[int] | None = None,
    ) -> str:
        """Take an action using a computer.

        Args:
          action: Action to take.
          text: Text related to the action
          coordinate: Coordinate related to the action.

        Returns:
          The sound that was passed to check.
        """
        return action

    return execute


@task
def hello_computer():
    return Task(
        dataset=[Sample(input="Call the computer tool with the action 'screenshot'")],
        solver=[
            use_tools([computer()]),
            generate(),
        ],
    )
