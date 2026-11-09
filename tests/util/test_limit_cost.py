from typing import Generator

import pytest
from test_helpers.limits import generate_with_retry_boundary

from inspect_ai.agent import Agent, AgentState, agent, run
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model._model import Model
from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
from inspect_ai.model._model_info import clear_model_info_cache, set_model_info
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util._limit import (
    LimitExceededError,
    check_cost_limit,
    cost_limit,
    record_model_cost,
    token_limit,
)


def test_can_record_model_cost_with_no_active_limits() -> None:
    record_model_cost(1.0)


def test_can_check_cost_limit_with_no_active_limits() -> None:
    check_cost_limit()


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        cost_limit(-1.0)


def test_can_create_with_none_limit() -> None:
    with cost_limit(None):
        _consume_cost(10.0)


def test_can_create_with_zero_limit() -> None:
    with cost_limit(0):
        pass


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    _consume_cost(10.0)

    with cost_limit(10.0):
        _consume_cost(10.0)


def test_raises_error_when_limit_exceeded() -> None:
    with cost_limit(0.01) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_cost(0.02)

    assert exc_info.value.type == "cost"
    assert exc_info.value.value == 0.02
    assert exc_info.value.limit == 0.01
    assert exc_info.value.source is limit


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    with cost_limit(0.01):
        _consume_cost(0.005)
        with pytest.raises(LimitExceededError):
            _consume_cost(0.006)


def test_can_get_and_update_limit_value() -> None:
    limit = cost_limit(0.01)
    assert limit.limit == 0.01

    with limit:
        _consume_cost(0.005)

        limit.limit = 0.02
        _consume_cost(0.015)

        limit.limit = 0.01

        with pytest.raises(LimitExceededError):
            check_cost_limit()

        limit.limit = None
        _consume_cost(5.0)

    assert limit.limit is None


def test_can_get_usage() -> None:
    limit = cost_limit(1.0)
    assert limit.usage == 0

    with limit:
        _consume_cost(0.5)
        assert limit.usage == 0.5

    assert limit.usage == 0.5


def test_stacking_cost_limits() -> None:
    outer = cost_limit(0.05)
    inner = cost_limit(0.01)

    with outer:
        _consume_cost(0.005)
        with inner:
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_cost(0.02)
            # inner limit should be the one that triggered
            assert exc_info.value.source is inner
            assert exc_info.value.limit == 0.01

    # outer tracked the full cost
    assert outer.usage == 0.025


def test_stacking_cost_limits_outer_exceeded() -> None:
    outer = cost_limit(0.01)
    inner = cost_limit(0.05)

    with outer:
        with inner:
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_cost(0.02)
            # outer limit should be the one that triggered (checked root to leaf)
            assert exc_info.value.source is outer
            assert exc_info.value.limit == 0.01


def _counting_model(calls: list[list[ChatMessage]]) -> Model:
    """A model which records each provider call."""

    def outputs(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        calls.append(input)
        return ModelOutput.from_content("mockllm/model", "hello")

    return get_model("mockllm/model", custom_outputs=outputs)


async def test_generate_refused_when_cost_limit_reached() -> None:
    calls: list[list[ChatMessage]] = []
    model = _counting_model(calls)

    with cost_limit(0.01) as limit:
        record_model_cost(0.01)
        with pytest.raises(LimitExceededError) as exc_info:
            await model.generate("")

    assert calls == []
    assert exc_info.value.type == "cost"
    assert exc_info.value.value == 0.01
    assert exc_info.value.limit == 0.01
    assert exc_info.value.source is limit
    assert exc_info.value.message.startswith("Cost limit reached.")


async def test_generate_dispatched_when_cost_limit_not_reached() -> None:
    calls: list[list[ChatMessage]] = []
    model = _counting_model(calls)

    with cost_limit(0.01):
        record_model_cost(0.005)
        await model.generate("")

    assert len(calls) == 1


async def test_generate_refused_when_outer_cost_limit_reached() -> None:
    calls: list[list[ChatMessage]] = []
    model = _counting_model(calls)

    with cost_limit(0.01) as outer:
        record_model_cost(0.01)
        with cost_limit(1.0):
            with pytest.raises(LimitExceededError) as exc_info:
                await model.generate("")

    assert calls == []
    assert exc_info.value.source is outer


async def test_generate_retry_refused_when_cost_limit_reached_in_on_stream() -> None:
    calls: list[list[ChatMessage]] = []

    with cost_limit(1.0) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            await generate_with_retry_boundary(calls, lambda: record_model_cost(1.0))

    # only the failed first attempt reached the provider
    assert len(calls) == 1
    assert exc_info.value.source is limit


@pytest.fixture
def ten_dollar_calls() -> Generator[None, None, None]:
    """Price mockllm/model so that each `_priced_model` call costs $10."""
    clear_model_info_cache()
    set_model_info(
        "model",
        ModelInfo(
            cost=ModelCost(
                input=5_000_000.0,
                output=5_000_000.0,
                input_cache_write=0.0,
                input_cache_read=0.0,
            )
        ),
    )
    yield
    clear_model_info_cache()


def _priced_model(calls: list[list[ChatMessage]]) -> Model:
    """A model whose calls each use 2 tokens (1 in, 1 out) and record the call."""

    def outputs(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        calls.append(input)
        output = ModelOutput.from_content("mockllm/model", "hello")
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    return get_model("mockllm/model", custom_outputs=outputs)


@pytest.mark.usefixtures("ten_dollar_calls")
async def test_cost_charged_when_child_token_limit_raises() -> None:
    calls: list[list[ChatMessage]] = []
    model = _priced_model(calls)

    @agent
    def one_call() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            await model.generate(state.messages)
            return state

        return execute

    with cost_limit(15.0) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            for _ in range(3):
                _, child_error = await run(one_call(), "hi", limits=[token_limit(1)])
                assert child_error is not None and child_error.type == "token"

    # the second call crossed the cost limit (its child token limit raised
    # first), so the third is refused before dispatch
    assert len(calls) == 2
    assert limit.usage == pytest.approx(20.0)
    assert exc_info.value.type == "cost"
    assert exc_info.value.source is limit


@pytest.mark.usefixtures("ten_dollar_calls")
async def test_token_limit_raise_charges_cost_once() -> None:
    calls: list[list[ChatMessage]] = []
    model = _priced_model(calls)

    with cost_limit(100.0) as limit:
        with token_limit(1):
            with pytest.raises(LimitExceededError) as exc_info:
                await model.generate("")

    assert exc_info.value.type == "token"
    assert len(calls) == 1
    assert limit.usage == pytest.approx(10.0)


def _consume_cost(amount: float) -> None:
    record_model_cost(amount)
    check_cost_limit()
