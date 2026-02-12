import tempfile
from random import randint
from typing import Generator

import anyio
import pytest
from test_helpers.limits import check_limit_event, find_limit_event
from test_helpers.utils import skip_if_no_docker, skip_if_no_openai, sleep_for_solver

from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
from inspect_ai.model._model_info import clear_model_info_cache, set_model_info
from inspect_ai.model._model_output import (
    ModelOutput,
    ModelUsage,
)
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._metrics import mean
from inspect_ai.scorer._scorer import Scorer, scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.solver._solver import Solver, generate
from inspect_ai.util._concurrency import concurrency
from inspect_ai.util._limit import sample_limits


@pytest.fixture(autouse=True)
def _clear_model_info() -> Generator[None, None, None]:
    clear_model_info_cache()
    yield
    clear_model_info_cache()


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
def token_consuming_scorer(model: Model, min_tokens: int) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        while state.token_usage < min_tokens:
            await model.generate("Hello")
        return Score(value=1)

    return score


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


def test_message_limit_reached_before_assistant_message():
    task = Task(
        dataset=[Sample(input="Say Hello only.", target="Hello")],
        solver=[generate()],
        scorer=match(),
        message_limit=1,  # 1 for user, 0 for assistant
    )

    log = eval(task, model="mockllm/model")[0]

    check_limit_event(log, "message")
    assert log.samples is not None
    assert len(log.samples[0].messages) == 1
    assert log.status == "success"


def test_message_limit_does_not_apply_to_scorer():
    @scorer(metrics=[mean()])
    def generating_scorer(model: Model) -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            for i in range(3):
                await model.generate(state.messages)
                state.messages.append(ChatMessageUser(content=f"Scorer {i}"))
                _ = state.completed

            return Score(value=1)

        return score

    model = get_model("mockllm/model")
    task = Task(
        dataset=[Sample(input="Say Hello only.", target="Hello")],
        solver=[],  # No solvers; straight to scorer.
        scorer=generating_scorer(model=model),
        # The message limit should only apply to the solvers, not the scorer.
        # Limit of 2 so that the 1 user message doesn't reach limit.
        message_limit=2,
    )

    log = eval(task, model=model)[0]

    assert find_limit_event(log) is None
    assert log.status == "success"
    assert log.samples[0].scores["generating_scorer"].value == 1


def test_token_limit():
    model = get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(mock_model_output(tokens=7)),
    )
    token_limit = 10
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(check_tokens=True),
        scorer=match(),
        token_limit=token_limit,
    )

    log = eval(task, model=model)[0]
    total_tokens = sum(usage.total_tokens for usage in log.stats.model_usage.values())
    assert total_tokens == 14
    check_limit_event(log, "token")


def test_token_limit_does_not_apply_to_scorer():
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput(usage=ModelUsage(total_tokens=20))],
    )
    token_limit = 10
    task = Task(
        dataset=[Sample(input="Say Hello only.", target="Hello")],
        solver=[],  # No solvers; straight to scorer.
        scorer=token_consuming_scorer(model=model, min_tokens=token_limit),
        # The token limit should only apply to the solvers, not the scorer.
        token_limit=token_limit,
    )

    log = eval(task, model=model)[0]
    total_tokens = sum(usage.total_tokens for usage in log.stats.model_usage.values())
    assert total_tokens > token_limit
    # Total tokens exceed the limit, but there are no limit events because it was only
    # exceeded by the scorer.
    assert find_limit_event(log) is None
    assert log.status == "success"


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


@skip_if_no_openai
def test_sample_limits_available_to_scorer():
    def check_limits() -> None:
        limits = sample_limits()
        assert limits.message.limit == 2
        assert limits.message.usage == 2
        assert limits.token.limit == 20
        # The model usually returns "Hello!" or "Hello.", but sometimes it returns
        # "Hello" - which is one fewer token.
        assert limits.token.usage in (12, 13)

    @scorer(metrics=[mean()])
    def limit_checking_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            check_limits()
            return Score(value=1)

        return score

    task = Task(
        dataset=[Sample(input="Say Hello only.", target="Hello")],
        solver=[generate()],
        cleanup=check_limits,
        scorer=limit_checking_scorer(),
        message_limit=2,
        token_limit=20,
    )

    log = eval(task, model="openai/gpt-4o")[0]
    assert log.status == "success"


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


@pytest.mark.slow
@skip_if_no_docker
def test_working_limit_does_not_raise_during_sandbox_teardown() -> None:
    # Historical issue: the working limit was not being disabled before sandbox
    # teardown. If the working limit was exceeded by the time of tearing down the
    # sandbox, we'd raise an error at the point of trying to acquire a semaphore before
    # calling out to Docker.
    working_limit = 1
    log = eval(
        Task(solver=sleep_for_solver(seconds=2)),
        model="mockllm/model",
        working_limit=working_limit,
        sandbox="docker",
    )[0]
    assert log.status == "success"


def check_working_limit_event(log: EvalLog, working_limit: int):
    assert log.eval.config.working_limit == working_limit
    assert log.samples
    assert log.samples[0].total_time
    assert log.samples[0].working_time
    assert log.samples[0].total_time > log.samples[0].working_time
    check_limit_event(log, "working")


def mock_model_output(tokens: int) -> ModelOutput:
    output = ModelOutput.from_content(model="mockllm", content="Hello")
    output.usage = ModelUsage(total_tokens=tokens)
    return output


def repeat_forever(output: ModelOutput) -> Generator[ModelOutput, None, None]:
    while True:
        yield output


def test_cost_limit() -> None:
    set_model_info(
        "model",
        ModelInfo(
            cost=ModelCost(
                input=1000.0,
                output=1000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    # 3 input + 4 output = 7 total tokens per call
    # Cost = (3 * 1000 + 4 * 1000) / 1M = $0.007 per call
    # Cost limit of $0.01 allows 1 call ($0.007) but not 2 ($0.014)
    output = ModelOutput.from_content(model="mockllm/model", content="Hello")
    output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    model = get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(output),
    )
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
    )
    log = eval(
        task,
        model=model,
        cost_limit=0.01,
    )[0]
    check_limit_event(log, "cost")


def test_cost_limit_without_cost_data_errors() -> None:
    with pytest.raises(PrerequisiteError, match="Missing cost data for"):
        eval(
            Task(
                dataset=[Sample(input="hi")],
                solver=[],
            ),
            model="mockllm/model",
            cost_limit=1.0,
        )


def test_model_without_cost_data_errors() -> None:
    # Register model info without cost data
    set_model_info("model", ModelInfo())
    with pytest.raises(
        PrerequisiteError,
        match="Missing cost data for",
    ):
        eval(
            Task(
                dataset=[Sample(input="hi")],
                solver=[],
            ),
            model="mockllm/model",
            cost_limit=1.0,
        )


def test_cost_data_without_cost_limit_tracks_cost() -> None:
    set_model_info(
        "model",
        ModelInfo(
            cost=ModelCost(
                input=1000.0,
                output=1000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    output = ModelOutput.from_content(model="mockllm/model", content="Hello")
    output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    model = get_model("mockllm/model", custom_outputs=[output])
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=[generate()],
        scorer=match(),
    )
    log = eval(
        task,
        model=model,
    )[0]
    assert log.status == "success"
    # (3 * 1000 + 4 * 1000) / 1_000_000 = 0.007
    usage = list(log.stats.model_usage.values())[0]
    assert usage.total_cost == pytest.approx(0.007)
    assert find_limit_event(log) is None


def test_two_models_both_with_cost_data_tracks_cost() -> None:
    set_model_info(
        "model",
        ModelInfo(
            cost=ModelCost(
                input=1000.0,
                output=1000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    set_model_info(
        "model2",
        ModelInfo(
            cost=ModelCost(
                input=2000.0,
                output=2000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    output1 = ModelOutput.from_content(model="mockllm/model", content="Hello")
    output1.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    output2 = ModelOutput.from_content(model="mockllm/model2", content="Hello")
    output2.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=[generate()],
        scorer=match(),
    )
    logs = eval(
        task,
        model=[
            get_model("mockllm/model", custom_outputs=[output1]),
            get_model("mockllm/model2", custom_outputs=[output2]),
        ],
    )
    assert len(logs) == 2
    for log in logs:
        assert log.status == "success"
        assert find_limit_event(log) is None
    # (3 * 1000 + 4 * 1000) / 1_000_000 = 0.007
    cost1 = list(logs[0].stats.model_usage.values())[0].total_cost
    assert cost1 == pytest.approx(0.007)
    # (3 * 2000 + 4 * 2000) / 1_000_000 = 0.014
    cost2 = list(logs[1].stats.model_usage.values())[0].total_cost
    assert cost2 == pytest.approx(0.014)


def test_task_level_cost_limit_without_cost_data_errors() -> None:
    with pytest.raises(PrerequisiteError, match="Missing cost data for"):
        eval(
            Task(
                dataset=[Sample(input="hi")],
                solver=[],
                cost_limit=1.0,
            ),
            model="mockllm/model",
        )


def test_task_level_cost_limit() -> None:
    set_model_info(
        "model",
        ModelInfo(
            cost=ModelCost(
                input=1000.0,
                output=1000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    # 3 input + 4 output = 7 total tokens per call
    # Cost = (3 * 1000 + 4 * 1000) / 1M = $0.007 per call
    # Cost limit of $0.01 allows 1 call ($0.007) but not 2 ($0.014)
    output = ModelOutput.from_content(model="mockllm/model", content="Hello")
    output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    model = get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(output),
    )
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        cost_limit=0.01,
    )
    log = eval(task, model=model)[0]
    check_limit_event(log, "cost")


def test_model_cost_config_file() -> None:
    # register model info without cost, then use config file to add cost
    set_model_info("model", ModelInfo())
    config_yaml = (
        "model:\n"
        "    input: 1000.0\n"
        "    output: 1000.0\n"
        "    input_cache_write: 0.0\n"
        "    input_cache_read: 0.0\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_yaml)
        config_path = f.name

    output = ModelOutput.from_content(model="mockllm/model", content="Hello")
    output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    model = get_model("mockllm/model", custom_outputs=[output])
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=[generate()],
        scorer=match(),
    )
    log = eval(
        task,
        model=model,
        model_cost_config=config_path,
    )[0]
    assert log.status == "success"
    usage = list(log.stats.model_usage.values())[0]
    assert usage.total_cost == pytest.approx(0.007)


def test_model_cost_config_dict() -> None:
    # register model info without cost, then use dict to add cost
    set_model_info("model", ModelInfo())
    output = ModelOutput.from_content(model="mockllm/model", content="Hello")
    output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
    model = get_model("mockllm/model", custom_outputs=[output])
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=[generate()],
        scorer=match(),
    )
    log = eval(
        task,
        model=model,
        model_cost_config={
            "model": ModelCost(
                input=1000.0,
                output=1000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        },
    )[0]
    assert log.status == "success"
    usage = list(log.stats.model_usage.values())[0]
    assert usage.total_cost == pytest.approx(0.007)
