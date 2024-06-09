from random import randint

from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, solver


@skip_if_no_openai
def test_max_messages_complete():
    @solver
    def max_messages_solver():
        async def solve(state: TaskState, generate: Generate):
            state = await generate(state)
            while not state.completed:
                state.messages.append(state.user_prompt)
                state = await generate(state)

            return state

        return solve

    max_messages = randint(1, 3) * 2
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        plan=max_messages_solver(),
        scorer=match(),
        max_messages=max_messages,
    )

    log = eval(task, model="openai/gpt-4")[0]
    assert len(log.samples[0].messages) == max_messages
