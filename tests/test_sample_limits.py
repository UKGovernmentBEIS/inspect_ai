import asyncio
from random import randint

from test_helpers.utils import skip_if_no_openai, sleep_for_solver

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import SampleLimitEvent
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._metrics import mean
from inspect_ai.scorer._scorer import Scorer, scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver import Generate, TaskState, solver


@solver
def looping_solver(check_tokens: bool = False):
    async def solve(state: TaskState, generate: Generate):
        # first generate
        state = await generate(state)

        # verify we are successfully tracking tokens if requested
        if check_tokens:
            assert state.token_usage > 0

        # keep generating until we hit a limit
        while not state.completed:
            state.messages.append(state.user_prompt)
            state = await generate(state)

        return state

    return solve


@scorer(metrics=[mean()])
def slow_scorer(seconds: int | None = 10) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        if seconds is not None:
            await asyncio.sleep(seconds)

        return Score(value=1)

    return score


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
    check_limit_event(log, "message")


@skip_if_no_openai
def test_token_limit_complete():
    token_limit = 10
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(check_tokens=True),
        scorer=match(),
        token_limit=token_limit,
    )
    model = "openai/gpt-4o-mini"

    log = eval(task, model=model)[0]
    total_tokens = log.stats.model_usage[model].total_tokens
    assert total_tokens > token_limit
    assert total_tokens < (token_limit * 3)
    check_limit_event(log, "token")


def test_time_limit():
    log = eval(Task(solver=sleep_for_solver(3)), model="mockllm/model", time_limit=2)[0]
    check_limit_event(log, "time")


def test_time_limit_scorer():
    log = eval(
        Task(scorer=slow_scorer()),
        model="mockllm/model",
        time_limit=2,
        fail_on_error=False,
    )[0]
    assert log.status == "success"
    check_limit_event(log, "time")


def test_solver_scorer_combined_timeout():
    log = eval(
        Task(solver=sleep_for_solver(1), scorer=slow_scorer(1)),
        model="mockllm/model",
        time_limit=3,
    )[0]
    assert log.status == "success"


def test_solver_scorer_combined_timeout_exceeded():
    log = eval(
        Task(solver=sleep_for_solver(1), scorer=slow_scorer(3)),
        model="mockllm/model",
        time_limit=3,
        fail_on_error=False,
    )[0]
    assert log.status == "success"
    check_limit_event(log, "time")


def test_solver_timeout_scored():
    log = eval(
        Task(solver=sleep_for_solver(2), scorer=slow_scorer(None)),
        model="mockllm/model",
        time_limit=1,
    )[0]
    assert log.status == "success"


def test_solver_timeout_not_scored():
    log = eval(
        Task(solver=sleep_for_solver(3), scorer=slow_scorer(2)),
        model="mockllm/model",
        time_limit=2,
    )[0]
    assert log.status == "error"


def check_limit_event(log: EvalLog, content: str) -> None:
    event = find_limit_event(log)
    assert event
    assert content == event.type


def find_limit_event(log: EvalLog) -> SampleLimitEvent | None:
    if log.samples:
        return next(
            (
                event
                for event in log.samples[0].events
                if isinstance(event, SampleLimitEvent)
            ),
            None,
        )
    else:
        return None
