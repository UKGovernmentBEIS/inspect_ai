from random import randint

from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import InfoEvent
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, solver


@solver
def looping_solver():
    async def solve(state: TaskState, generate: Generate):
        state = await generate(state)
        while not state.completed:
            state.messages.append(state.user_prompt)
            state = await generate(state)

        return state

    return solve


def test_message_limit_complete():
    message_limit = randint(1, 3) * 2
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        message_limit=message_limit,
    )

    log = eval(task, model="mockllm/model")[0]
    assert len(log.samples[0].messages) == message_limit
    check_info_event(log, "exceeded message limit")


@skip_if_no_openai
def test_token_limit_complete():
    token_limit = 10
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        token_limit=token_limit,
    )
    model = "openai/gpt-4o-mini"

    log = eval(task, model=model)[0]
    total_tokens = log.stats.model_usage[model].total_tokens
    assert total_tokens > token_limit
    assert total_tokens < (token_limit * 3)
    check_info_event(log, "exceeded token limit")


def check_info_event(log: EvalLog, content: str) -> None:
    event = find_info_event(log)
    assert event
    assert content in str(event.data)


def find_info_event(log: EvalLog) -> InfoEvent | None:
    if log.samples:
        return next(
            (
                event
                for event in log.samples[0].transcript.events
                if isinstance(event, InfoEvent)
            ),
            None,
        )
    else:
        return None
