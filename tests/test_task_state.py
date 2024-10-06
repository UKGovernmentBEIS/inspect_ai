from random import randint

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, solver


def test_message_limit_complete():
    @solver
    def message_limit_solver():
        async def solve(state: TaskState, generate: Generate):
            state = await generate(state)
            while not state.completed:
                state.messages.append(state.user_prompt)
                state = await generate(state)

            return state

        return solve

    message_limit = randint(1, 3) * 2
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=message_limit_solver(),
        scorer=match(),
        message_limit=message_limit,
    )

    log = eval(task, model="mockllm/model")[0]
    assert len(log.samples[0].messages) == message_limit
