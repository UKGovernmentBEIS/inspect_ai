import functools
import tempfile
from pathlib import Path
from random import randint
from typing import Any, Generator

import anyio
import pytest
from test_helpers.limits import check_limit_event, find_limit_event
from test_helpers.tools import addition
from test_helpers.utils import (
    flaky_retry,
    skip_if_no_anthropic,
    skip_if_no_docker,
    skip_if_no_google,
    skip_if_no_openai,
    sleep_for_solver,
)

from inspect_ai import Task, eval
from inspect_ai._util._async import tg_collect
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import _registry
from inspect_ai._util.working import add_sample_wait, sample_clock
from inspect_ai.approval import (
    Approval,
    ApprovalPolicy,
    Approver,
    approver,
    auto_approver,
)
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent, SubtaskEvent, ToolEvent
from inspect_ai.log._log import EvalLog, EvalSample
from inspect_ai.log._samples import awaiting_human
from inspect_ai.model import ChatMessage, ChatMessageAssistant, GenerateConfig, ModelAPI
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
from inspect_ai.model._model_info import clear_model_info_cache, set_model_info
from inspect_ai.model._model_output import (
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._registry import modelapi
from inspect_ai.scorer import match
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._metrics import mean
from inspect_ai.scorer._scorer import Scorer, scorer
from inspect_ai.scorer._target import Target
from inspect_ai.solver import Generate, TaskState, solver, use_tools
from inspect_ai.solver._solver import Solver, generate
from inspect_ai.tool import Tool, ToolCall, ToolCallView, ToolChoice, ToolInfo, tool
from inspect_ai.util import subtask
from inspect_ai.util._concurrency import concurrency
from inspect_ai.util._limit import TokenLimit, sample_limits, suspend_working_limit


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


def test_token_limit_reached_exactly_refuses_next_generate():
    model = get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(mock_model_output(tokens=5)),
    )
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        token_limit=10,
    )

    log = eval(task, model=model)[0]
    # two calls reach the limit exactly; the third is refused before it is sent
    total_tokens = sum(usage.total_tokens for usage in log.stats.model_usage.values())
    assert total_tokens == 10
    event = find_limit_event(log)
    assert event is not None and event.type == "token"
    assert event.message == "Token limit reached. value: 10; limit: 10"


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


def test_output_token_limit():
    output = ModelOutput.from_content(model="mockllm", content="Hello")
    output.usage = ModelUsage(input_tokens=10, output_tokens=2, total_tokens=12)
    model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        token_limit=TokenLimit(tokens=5, type="output"),
    )

    log = eval(task, model=model)[0]
    usage = log.stats.model_usage["mockllm/model"]
    # total tokens exceed 5 on the first generation: only output tokens are
    # metered, so the limit trips on the 3rd generation (6 output tokens)
    assert usage.output_tokens == 6
    assert usage.total_tokens == 36
    check_limit_event(log, "token")
    # the config records the decomposed (limit, type) pair
    assert log.eval.config.token_limit == 5
    assert log.eval.config.token_limit_type == "output"


def test_output_token_limit_string_form():
    output = ModelOutput.from_content(model="mockllm", content="Hello")
    output.usage = ModelUsage(input_tokens=10, output_tokens=2, total_tokens=12)
    model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
    )

    log = eval(task, model=model, token_limit="output:5")[0]
    check_limit_event(log, "token")
    assert log.eval.config.token_limit == 5
    assert log.eval.config.token_limit_type == "output"


def test_formula_token_limit():
    output = ModelOutput.from_content(model="mockllm", content="Hello")
    output.usage = ModelUsage(input_tokens=100, output_tokens=2, total_tokens=102)
    model = get_model("mockllm/model", custom_outputs=repeat_forever(output))
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        # meters input*0.1 + output; per generation = 10 + 2 = 12
        token_limit=TokenLimit(tokens=20, type="(input * 0.1) + output"),
    )

    log = eval(task, model=model)[0]
    # gen 1: 12 (<=20); gen 2: 24 (>20) -> trips
    check_limit_event(log, "token")
    assert log.eval.config.token_limit == 20
    assert log.eval.config.token_limit_type == "(input * 0.1) + output"


def test_token_limit_type_absent_for_int_limit():
    model = get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(mock_model_output(tokens=7)),
    )
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        token_limit=10,
    )

    log = eval(task, model=model)[0]
    assert log.eval.config.token_limit == 10
    assert log.eval.config.token_limit_type is None
    # serialized config omits the type field entirely (old-log compatibility)
    assert "token_limit_type" not in log.eval.config.model_dump_json(exclude_none=True)


def test_turn_limit():
    model = get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(mock_model_output(tokens=1)),
    )
    turn_limit = 2
    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=looping_solver(),
        scorer=match(),
        turn_limit=turn_limit,
    )

    log = eval(task, model=model)[0]
    # turn_limit(2) allows 2 generations; the 3rd records the turn and exceeds.
    total_generations = sum(
        usage.total_tokens for usage in log.stats.model_usage.values()
    )
    assert total_generations == 3
    check_limit_event(log, "turn")
    # The limit which halted the sample is recorded on the sample.
    assert log.samples
    assert log.samples[0].limit is not None
    assert log.samples[0].limit.type == "turn"
    assert log.samples[0].limit.limit == turn_limit
    assert log.samples[0].limit.reason == "Turn limit exceeded. value: 3; limit: 2"


def test_turn_limit_does_not_apply_to_scorer():
    @scorer(metrics=[mean()])
    def generating_scorer(model: Model) -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            # Many generations in the scorer must not count against the turn limit.
            for _ in range(5):
                await model.generate("Hello")
            return Score(value=1)

        return score

    model = get_model(
        "mockllm/model",
        custom_outputs=[mock_model_output(tokens=1) for _ in range(5)],
    )
    task = Task(
        dataset=[Sample(input="Say Hello only.", target="Hello")],
        solver=[],  # No solvers; straight to scorer.
        scorer=generating_scorer(model=model),
        # The turn limit should only apply to the solvers, not the scorer.
        turn_limit=1,
    )

    log = eval(task, model=model)[0]

    assert find_limit_event(log) is None
    assert log.status == "success"
    assert log.samples[0].scores["generating_scorer"].value == 1


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
@flaky_retry(max_retries=3)
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
    assert log.samples[0].total_time >= log.samples[0].working_time
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


def test_cost_data_keyed_by_full_model_string_tracks_cost() -> None:
    # Regression for routed providers (together, hf-inference-providers, custom
    # routed providers): set_model_info / set_model_cost / --model-cost-config key
    # cost under the user-facing model string, which differs from canonical_name()
    # when the provider strips a route prefix. mockllm reproduces the mismatch:
    # str(model) is "mockllm/model" but canonical_name() is "model", so registering
    # under the full string must still be found when recording usage.
    set_model_info(
        "mockllm/model",
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


def test_operator_limit_records_reason() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="addition",
                tool_arguments={"x": 1, "y": 1},
            ),
            ModelOutput.from_content("mockllm/model", content="2"),
        ],
    )
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        scorer=match(numeric=True),
        approval=[ApprovalPolicy(approver=auto_approver("terminate"), tools="*")],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples

    # the terminating approver's reason reaches the sample's own record, not
    # just the transcript event — 'operator' alone doesn't say which
    # termination this was
    limit = log.samples[0].limit
    assert limit is not None
    assert limit.type == "operator"
    assert limit.reason == "Tool call approver requested termination."

    # and survives into the summary, the cheap read path
    summary = log.samples[0].summary()
    assert summary.limit == "operator"
    assert summary.limit_reason == "Tool call approver requested termination."


# Working time under concurrent and late-known waits
# (design/working-time-concurrency.md). These run real samples with short
# real sleeps; the retry backoff sleep is shortened through `_sleep`.

_BACKOFF = 0.3


class _FlakyError(Exception):
    pass


class _FlakyAPI(ModelAPI):
    """Fails each distinct input `fail_times` times, then succeeds."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        fail_times: int = 0,
        attempt_seconds: float = 0.1,
        call_time: float | None = None,
        return_call: bool = False,
        **model_args: object,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key="flaky",
            api_key_vars=[],
            config=config,
        )
        self.fail_times = fail_times
        self.attempt_seconds = attempt_seconds
        self.call_time = call_time
        self.return_call = return_call
        self.attempts: dict[str, int] = {}

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput, ModelCall]:
        key = input[-1].text
        self.attempts[key] = self.attempts.get(key, 0) + 1
        await anyio.sleep(self.attempt_seconds)
        if self.attempts[key] <= self.fail_times:
            raise _FlakyError(f"attempt {self.attempts[key]} failed")
        output = ModelOutput.from_content(model=self.model_name, content="ok")
        if self.call_time is not None or self.return_call:
            return output, ModelCall.create({}, {}, time=self.call_time)
        return output

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, _FlakyError)


@pytest.fixture
def flaky_model(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    async def short_sleep(seconds: float) -> None:
        await anyio.sleep(_BACKOFF)

    monkeypatch.setattr("inspect_ai.model._retry._sleep", short_sleep)

    @modelapi(name="flakytiming")
    def flakytiming() -> type[ModelAPI]:
        return _FlakyAPI

    yield
    del _registry["modelapi:flakytiming"]


def _run_timing_solver(solver: Solver, **eval_args: Any) -> EvalSample:
    log = eval(Task(solver=solver), model="mockllm/model", **eval_args)[0]
    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.total_time is not None and sample.working_time is not None
    assert 0 <= sample.working_time <= sample.total_time
    return sample


def _waiting(sample: EvalSample) -> float:
    assert sample.total_time is not None and sample.working_time is not None
    return sample.total_time - sample.working_time


def test_concurrent_retries_working_time_not_negative(flaky_model: None) -> None:
    """Concurrent retries merge their waits instead of adding them."""

    @solver
    def concurrent_retries() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = get_model("flakytiming/m", fail_times=2, memoize=False)
            await tg_collect(
                [functools.partial(model.generate, f"call {i}") for i in range(4)]
            )
            return state

        return solve

    sample = _run_timing_solver(concurrent_retries())
    # each call: two failed 0.1 s attempts and two backoffs, then success
    assert _waiting(sample) >= 2 * (0.1 + _BACKOFF) - 0.05


def test_semaphore_waiter_merges() -> None:
    """A task waiting on a semaphore makes the whole sample wait."""

    @solver
    def semaphore_wait() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            held = anyio.Event()

            async def holder() -> None:
                async with concurrency("working-time-k", 1):
                    held.set()
                    await anyio.sleep(0.5)

            async def waiter() -> None:
                await held.wait()
                async with concurrency("working-time-k", 1):
                    pass

            await tg_collect([holder, waiter])
            return state

        return solve

    sample = _run_timing_solver(semaphore_wait())
    assert _waiting(sample) >= 0.4


def test_cache_hit_adds_no_waiting(
    flaky_model: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A cache hit credits nothing (it used to credit the original call's time)."""
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))

    @solver
    def cached_twice() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = get_model("flakytiming/m", attempt_seconds=0.3, memoize=False)
            await model.generate("same", cache=True)
            await model.generate("same", cache=True)
            return state

        return solve

    sample = _run_timing_solver(cached_twice())
    assert _waiting(sample) < 0.1


def test_attempts_of_call_that_runs_out_of_retries_are_waiting(
    flaky_model: None,
) -> None:
    @solver
    def exhausted() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = get_model(
                "flakytiming/m",
                fail_times=100,
                attempt_seconds=0.2,
                config=GenerateConfig(max_retries=1),
                memoize=False,
            )
            with pytest.raises(Exception):
                await model.generate("fails")
            return state

        return solve

    sample = _run_timing_solver(exhausted())
    # two retryable attempts and one backoff
    assert _waiting(sample) >= 2 * 0.2 + _BACKOFF - 0.05


def test_sdk_internal_retries_are_waiting(flaky_model: None) -> None:
    """An attempt's time before its successful request is waiting."""

    @solver
    def sdk_retry() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = get_model(
                "flakytiming/m", attempt_seconds=0.5, call_time=0.1, memoize=False
            )
            await model.generate("sdk")
            return state

        return solve

    sample = _run_timing_solver(sdk_retry())
    assert _waiting(sample) >= 0.35
    # the successful 0.1 s request is working time
    assert sample.working_time is not None and sample.working_time >= 0.09


@pytest.mark.parametrize(
    "call_args",
    [
        {"call_time": 0.0},  # placeholder used by SageMaker and hook fallbacks
        {"return_call": True},  # a ModelCall with no time
        {},  # no ModelCall
    ],
)
def test_unmeasured_successful_request_is_working(
    flaky_model: None, call_args: dict[str, Any]
) -> None:
    """Without a positive request time the whole successful attempt is working."""

    @solver
    def unmeasured() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = get_model(
                "flakytiming/m", attempt_seconds=0.4, memoize=False, **call_args
            )
            await model.generate("unmeasured")
            return state

        return solve

    sample = _run_timing_solver(unmeasured())
    assert _waiting(sample) < 0.1
    assert sample.working_time is not None and sample.working_time >= 0.39


def test_events_inside_suspension_have_zero_working_time() -> None:
    """Tools and subtasks wholly inside `suspend_working_limit()` log 0, never less."""

    @subtask
    async def quick_subtask() -> str:
        await anyio.sleep(0.001)
        return "done"

    @solver
    def suspended() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with suspend_working_limit():
                for _ in range(30):
                    await execute_tools(_tool_calls("_quick_tool"), [_quick_tool()])
                    await quick_subtask()
            return state

        return solve

    sample = _run_timing_solver(suspended())
    events = [e for e in sample.events if isinstance(e, ToolEvent | SubtaskEvent)]
    assert len(events) == 60
    for event in events:
        assert event.working_time == 0


@tool
def _quick_tool() -> Tool:
    async def execute() -> str:
        """Quick tool."""
        await anyio.sleep(0.001)
        return "quick"

    return execute


@tool
def _fast_tool() -> Tool:
    async def execute() -> str:
        """Fast tool."""
        await anyio.sleep(0.1)
        return "fast"

    return execute


def _tool_calls(*functions: str) -> list[ChatMessage]:
    return [
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id=function, function=function, arguments={})
                for function in functions
            ],
        )
    ]


def test_events_use_waits_inside_their_own_interval() -> None:
    """Tools and subtasks charge only the waits inside their own interval.

    A wait from the solver's start is known only once the slow tool and the
    subtask are running and the fast tool has completed. The fast tool keeps
    its published duration; the slow tool and the subtask subtract the part
    of the wait inside their own interval.
    """
    slow_started = anyio.Event()
    sub_started = anyio.Event()

    @tool
    def slow_tool() -> Tool:
        async def execute() -> str:
            """Slow tool."""
            slow_started.set()
            await anyio.sleep(0.8)
            return "slow"

        return execute

    @subtask
    async def slow_subtask() -> str:
        sub_started.set()
        await anyio.sleep(0.8)
        return "done"

    @solver
    def straddle() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            start = sample_clock()
            fast_done = anyio.Event()

            async def classify_late() -> None:
                await slow_started.wait()
                await sub_started.wait()
                await fast_done.wait()
                await anyio.sleep(0.3)
                add_sample_wait(start, sample_clock())

            async def run_slow() -> None:
                await execute_tools(_tool_calls("slow_tool"), [slow_tool()])

            async def run_fast() -> None:
                await execute_tools(_tool_calls("_fast_tool"), [_fast_tool()])
                fast_done.set()

            await tg_collect([classify_late, run_slow, run_fast, slow_subtask])
            return state

        return solve

    sample = _run_timing_solver(straddle())
    tools = {e.id: e for e in sample.events if isinstance(e, ToolEvent)}
    (sub,) = [e for e in sample.events if isinstance(e, SubtaskEvent)]
    slow, fast = tools["slow_tool"], tools["_fast_tool"]
    # the fast tool completed before the wait was known
    assert _event_waiting(fast) == pytest.approx(0, abs=0.01)
    # the slow tool and the subtask subtract at least the 0.3 s after they started
    assert 0.25 <= _event_waiting(slow) <= 0.8
    assert 0.25 <= _event_waiting(sub) <= 0.8


def _event_waiting(event: ToolEvent | SubtaskEvent) -> float:
    assert event.completed is not None and event.working_time is not None
    return (event.completed - event.timestamp).total_seconds() - event.working_time


@approver(name="working_time_slow_approver")
def _slow_approver() -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        await anyio.sleep(0.4)
        return Approval(decision="approve")

    return approve


def test_approval_is_waiting() -> None:
    @solver
    def approved_tool() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await execute_tools(
                _tool_calls("_fast_tool"),
                [_fast_tool()],
                approval=[ApprovalPolicy(approver=_slow_approver(), tools="*")],
            )
            return state

        return solve

    sample = _run_timing_solver(approved_tool())
    assert _waiting(sample) >= 0.35
    (event,) = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert event.working_time is not None and event.working_time < 0.3


def test_human_input_is_waiting() -> None:
    @solver
    def ask_human() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with awaiting_human("question"):
                await anyio.sleep(0.4)
            return state

        return solve

    sample = _run_timing_solver(ask_human())
    assert _waiting(sample) >= 0.35


def _check_live_working_time(model: str) -> None:
    """Successful live requests stay charged and working time stays in range.

    The sample's waiting time may only include what the provider SDK spent
    outside the successful request, so it can't exceed the clock time left
    after the model events' request times.
    """

    @solver
    def two_generates() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            for prompt in ("Say hello.", "Say goodbye."):
                await get_model(model).generate(prompt)
            return state

        return solve

    sample = _run_timing_solver(two_generates())
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 2
    request_time = sum(e.working_time or 0 for e in model_events)
    assert request_time > 0
    assert sample.working_time is not None and sample.working_time >= request_time
    assert sample.total_time is not None
    assert _waiting(sample) <= sample.total_time - request_time


@skip_if_no_openai
def test_live_openai_working_time() -> None:
    _check_live_working_time("openai/gpt-4o-mini")


@skip_if_no_anthropic
def test_live_anthropic_working_time() -> None:
    _check_live_working_time("anthropic/claude-haiku-4-5")


@skip_if_no_google
def test_live_google_working_time() -> None:
    _check_live_working_time("google/gemini-2.5-flash")
