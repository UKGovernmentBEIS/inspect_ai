import asyncio

import pytest

from inspect_ai.model._model import sample_model_usage
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError
from inspect_ai.util._limit import TokenLimit, check_token_limit


@pytest.fixture
def model_usage() -> ModelUsage:
    return _init_model_usage()


def test_validates_budget_parameter() -> None:
    with pytest.raises(ValueError):
        TokenLimit(-1)


def test_can_create_with_none_budget() -> None:
    with TokenLimit(None):
        check_token_limit()


def test_raises_error_when_limit_exceeded(model_usage: ModelUsage) -> None:
    with TokenLimit(10):
        model_usage.total_tokens = 11
        with pytest.raises(SampleLimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_repeatedly_exceeded(
    model_usage: ModelUsage,
) -> None:
    with TokenLimit(10):
        model_usage.total_tokens = 11
        with pytest.raises(SampleLimitExceededError):
            check_token_limit()
        model_usage.total_tokens += 1
        with pytest.raises(SampleLimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 12
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_exceeded_incrementally(
    model_usage: ModelUsage,
) -> None:
    with TokenLimit(10):
        model_usage.total_tokens += 5
        check_token_limit()
        with pytest.raises(SampleLimitExceededError):
            model_usage.total_tokens += 6
            check_token_limit()


def test_does_not_raise_error_when_limit_not_exceeded(model_usage: ModelUsage) -> None:
    model_usage.total_tokens = 10

    with TokenLimit(10):
        model_usage.total_tokens += 10
        check_token_limit()


def test_stack_can_trigger_outer_limit(model_usage: ModelUsage) -> None:
    model_usage.total_tokens = 5

    with TokenLimit(10):
        model_usage.total_tokens += 6
        check_token_limit()

        with TokenLimit(11):
            model_usage.total_tokens += 5
            # Should trigger outer limit (10).
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit(model_usage: ModelUsage) -> None:
    model_usage.total_tokens = 5

    with TokenLimit(10):
        model_usage.total_tokens += 1
        check_token_limit()

        with TokenLimit(5):
            model_usage.total_tokens += 6
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked(model_usage: ModelUsage) -> None:
    with TokenLimit(10):
        model_usage.total_tokens += 5
        check_token_limit()

    model_usage.total_tokens += 100
    check_token_limit()


def test_can_reuse_context_manager(model_usage: ModelUsage) -> None:
    limit = TokenLimit(10)

    with limit:
        model_usage.total_tokens += 10
        check_token_limit()

    with limit:
        model_usage.total_tokens += 10
        check_token_limit()

    with limit:
        model_usage.total_tokens += 11
        with pytest.raises(SampleLimitExceededError):
            check_token_limit()

    with limit:
        model_usage.total_tokens += 10
        check_token_limit()


def test_can_open_same_context_manager_multiple_times(model_usage: ModelUsage) -> None:
    limit = TokenLimit(10)

    with limit:
        model_usage.total_tokens += 10
        check_token_limit()

        with limit:
            model_usage.total_tokens += 10
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.value == 20


async def test_across_async_contexts():
    async def async_task():
        model_usage = _init_model_usage()
        model_usage.total_tokens = 5

        with TokenLimit(10):
            for _ in range(10):
                model_usage.total_tokens += 1
                check_token_limit()
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)

    await asyncio.gather(*(async_task() for _ in range(3)))


async def test_same_context_manager_across_async_contexts():
    async def async_task(limit: TokenLimit):
        model_usage = _init_model_usage()
        model_usage.total_tokens = 5

        with limit:
            # Incrementally use 10 tokens (should not exceed the limit).
            for _ in range(10):
                model_usage.total_tokens += 1
                check_token_limit()
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)

    # The same TokenLimit instance is reused across different async contexts.
    reused_context_manager = TokenLimit(10)
    await asyncio.gather(*(async_task(reused_context_manager) for _ in range(3)))


def test_can_update_limit_value(model_usage: ModelUsage) -> None:
    limit = TokenLimit(10)

    with limit:
        model_usage.total_tokens += 5
        check_token_limit()

        limit.limit = 20
        model_usage.total_tokens += 15
        check_token_limit()

        with pytest.raises(SampleLimitExceededError) as exc_info:
            # Note: the exception is raised as soon as we decrease the limit.
            limit.limit = 10

    assert exc_info.value.value == 20
    assert limit.limit == 10


def test_can_update_limit_value_on_reused_context_manager(
    model_usage: ModelUsage,
) -> None:
    shared_limit = TokenLimit(10)

    with shared_limit:
        model_usage.total_tokens += 10
        check_token_limit()

        with shared_limit:
            shared_limit.limit = 20

            model_usage.total_tokens += 10
            check_token_limit()

            model_usage.total_tokens += 10
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.value == 30


def _init_model_usage() -> ModelUsage:
    # Initialize the model usage context var and create an empty fictitious "model"
    # usage object.
    usage_dict = sample_model_usage()
    model_usage = ModelUsage()
    usage_dict["model"] = model_usage
    return model_usage
