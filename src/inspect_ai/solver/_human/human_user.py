import asyncio

from textual.app import ComposeResult
from textual.widgets import Link

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import InputPanel, input_panel


@solver
def human_user() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # copy scripts to sandbox

        # open input panel for control/progress
        async with await input_panel("User", HumanUserPanel):
            # run sandbox service

            await asyncio.sleep(5)

        await asyncio.sleep(3)
        return state

    return solve


class HumanUserPanel(InputPanel):
    def compose(self) -> ComposeResult:
        yield Link(
            "Go to textualize.io",
            url="https://textualize.io",
            tooltip="Click me",
        )
