import asyncio
from typing import cast

from inspect_ai.util import input_panel, sandbox

from .._solver import Generate, Solver, solver
from .._task_state import TaskState
from .panel import HumanUserPanel
from .sandbox import configure_sandbox


@solver
def human_user() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # configure sandbox
        await configure_sandbox()

        # open input panel for control/progress
        async with await input_panel("User", HumanUserPanel) as panel:
            panel = cast(HumanUserPanel, panel)

            panel.connection = await sandbox().connection()
            # run sandbox service

            # sleep forever
            await asyncio.sleep(5000)

        return state

    return solve
