from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    basic_agent,
    fork,
    solver,
)

PROMPT = """Write 10 x 1000 word essays about anything. Write and send the first essay, you will be prompted to continue and write the next. Once you have written all 10. Use the submit() tool and say 'I have written 10 essays'"""


def toy_data():
    return [Sample(input=PROMPT, target="10 x 1000 word essays about anything")]


@solver
def toy_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        states = await fork(
            state,
            [basic_agent() for i in range(3)],
        )

        return states[0]

    return solve


@task
def toy() -> Task:
    solver = toy_solver()
    grader = model_graded_qa(include_history=True)
    return Task(
        dataset=toy_data(),
        scorer=grader,
        solver=solver,
        token_limit=1000,
        fail_on_error=False,
    )
