
from inspect_ai import Task, eval
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@solver
def big_output_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate):

        await sandbox().exec(["python", "-c", """#!/usr/bin/env python
import random
import string

foo_big = ""

for _ in range(1000):
    foo = ''.join(random.choices(string.ascii_letters + string.digits, k=1_000_000))
    print(foo)
    foo_big += foo
    print(len(foo_big))
            """])
        state.completed = True
        return state

    return solve

def test_max_exec_output():

    task = Task(
        dataset=[
            Sample(
                input="Do whatever",
            )
        ],
        solver=big_output_solver(),
        config=GenerateConfig(max_tool_output=5),
    )

    log = eval(task, model="mockllm/model", sandbox="docker")[0]

    assert log.error

