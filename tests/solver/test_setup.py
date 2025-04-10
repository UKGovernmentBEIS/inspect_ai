from inspect_ai import Task, eval
from inspect_ai.solver import (
    Generate,
    TaskState,
    solver,
)


@solver
def setup():
    async def solve(state: TaskState, _generate: Generate):
        state.store.set("setup", True)
        return state

    return solve


def test_solver_setup():
    log = eval(Task(setup=setup()), model="mockllm/model")[0]
    assert log.samples
    assert log.samples[0].store.get("setup") is True
