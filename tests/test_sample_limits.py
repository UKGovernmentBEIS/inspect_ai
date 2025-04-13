from random import randint

import anyio
from test_helpers.utils import skip_if_no_openai, sleep_for_solver

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import SampleLimitEvent
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._metrics import mean
from inspect_ai.scorer._scorer import Scorer, scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.solver._solver import Solver
from inspect_ai.util._concurrency import concurrency


@solver
def looping_solver(check_tokens: bool = False, sleep_for: float | None = None):
    async def solve(state: TaskState, generate: Generate):
        # first generate
        state = await generate(state)

        # verify we are successfully tracking tokens if requested
        if check_tokens:
            assert state.token_usage > 0

        # keep generating until we hit a limit
        while True:
            if sleep_for:
                await anyio.sleep(sleep_for)
            state.messages.append(state.user_prompt)
            state = await generate(state)

        return state

    return solve


@solver
def looping_concurrecy_solver():
    async def solve(state: TaskState, generate: Generate):
        # simulate waiting for shared resource
        async with concurrency("shared-resource", 1):
            await anyio.sleep(1)

        return state

    return solve


@solver
def appending_solver():
    async def solve(state: TaskState, generate: Generate):
        # keep appending until we hit a limit
        while True:
            state.messages.append(ChatMessageUser(content="hello"))

        return state

    return solve


@solver
def overwriting_solver():
    async def solve(state: TaskState, generate: Generate):
        # keep overwriting with an increasing number of messages until we hit a limit
        while True:
            state.messages = state.messages + [ChatMessageUser(content="message")]

        return state

    return solve


@scorer(metrics=[mean()])
def slow_scorer(seconds: int | None = 10) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        if seconds is not None:
            await anyio.sleep(seconds)

        return Score(value=1)

    return score


def check_message_limit(solver: Solver):
    message_limit = randint(1, 3) * 2
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=solver,
        scorer=match(),
        message_limit=message_limit,
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples[0].messages) == message_limit
    check_limit_event(log, "message")


def test_message_limit_generate():
    check_message_limit(looping_solver())


def test_message_limit_append():
    check_message_limit(appending_solver())


def test_message_limit_overwrite():
    check_message_limit(overwriting_solver())


@skip_if_no_openai
def test_token_limit():
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


def test_working_limit():
    working_limit = 3
    log = eval(
        Task(solver=looping_solver(sleep_for=1)),
        model="mockllm/model",
        working_limit=working_limit,
    )[0]
    check_working_limit_event(log, working_limit)


def test_working_limit_reporting():
    log = eval(
        Task(
            dataset=[Sample(id=id, input=f"Input for {id}") for id in range(0, 3)],
            solver=looping_concurrecy_solver(),
        ),
        model="mockllm/model",
    )[0]
    assert log.samples
    waiting_time = 0
    for sample in log.samples:
        waiting_time += sample.total_time - sample.working_time + 0.1
    assert waiting_time > 3


def check_working_limit_event(log: EvalLog, working_limit: int):
    assert log.eval.config.working_limit == working_limit
    assert log.samples
    assert log.samples[0].total_time
    assert log.samples[0].working_time
    assert log.samples[0].total_time > log.samples[0].working_time
    check_limit_event(log, "working")


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
