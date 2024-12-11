import asyncio

from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import input_panel, sandbox

from .panel import HumanAgentPanel
from .sandbox import configure_sandbox

# TODO: add a panel that can show when we get shell commands
# TODO: fill out the shell commands and the instructions


@solver
def human_agent() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # get sandbox connection
        connection = await sandbox().connection()

        # configure sandbox
        await configure_sandbox()

        # open input panel for control/progress
        async with await input_panel(HumanAgentPanel) as panel:
            # configure panel
            panel.connection = connection

            # run sandbox service

            # sleep forever
            await asyncio.sleep(5000)

        return state

    return solve
