# import asyncio

from inspect_ai import Task, eval
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox_service


@solver
def service_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # asyncio.get_running_loop().call_at()

        await sandbox_service("foo", {}, lambda: state.store.get("foo:complete", False))

        return state

    return solve


def test_sandbox_service():
    log = eval(Task(solver=service_solver(), sandbox="local"))[0]
