import asyncio
from typing import Generator

import pytest

from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._counter import (
    get_counter_leaf_node,
    model_usage_counter,
    record_model_usage,
)
from inspect_ai.util._limit import (
    SampleLimitExceededError,
    TokenLimit,
    check_token_limit,
    has_token_limit_been_exceeded,
)


@pytest.fixture(autouse=True)
def counter() -> Generator[None, None, None]:
    with model_usage_counter("scope"):
        yield


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        TokenLimit(-1)


def test_can_create_with_none_limit() -> None:
    with TokenLimit(None):
        check_token_limit()


def usage(total_tokens: int) -> ModelUsage:
    return ModelUsage(total_tokens=total_tokens)


def _record_token_usage(total_tokens: int) -> None:
    record_model_usage("model", ModelUsage(total_tokens=total_tokens))


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    _record_token_usage(10)

    with TokenLimit(10):
        _record_token_usage(10)
        check_token_limit()


def test_raises_error_when_limit_exceeded() -> None:
    with TokenLimit(10):
        _record_token_usage(11)
        with pytest.raises(SampleLimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_repeatedly_exceeded() -> None:
    with TokenLimit(10):
        _record_token_usage(11)
        with pytest.raises(SampleLimitExceededError):
            check_token_limit()
        _record_token_usage(1)
        with pytest.raises(SampleLimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 12
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    with TokenLimit(10):
        _record_token_usage(5)
        check_token_limit()
        with pytest.raises(SampleLimitExceededError):
            _record_token_usage(6)
            check_token_limit()


def test_has_token_limit_been_exceeded() -> None:
    with TokenLimit(10):
        while not has_token_limit_been_exceeded():
            _record_token_usage(1)

    assert get_counter_leaf_node().get_total_sum() == 11


def test_stack_can_trigger_outer_limit() -> None:
    _record_token_usage(5)

    with TokenLimit(10):
        _record_token_usage(6)
        check_token_limit()

        with TokenLimit(11):
            _record_token_usage(5)
            # Should trigger outer limit (10).
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit() -> None:
    _record_token_usage(5)

    with TokenLimit(10):
        _record_token_usage(1)
        check_token_limit()

        with TokenLimit(5):
            _record_token_usage(6)
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked() -> None:
    with TokenLimit(10):
        _record_token_usage(5)
        check_token_limit()

    _record_token_usage(100)
    check_token_limit()


def test_can_reuse_context_manager() -> None:
    limit = TokenLimit(10)

    with limit:
        _record_token_usage(10)
        check_token_limit()

    with limit:
        _record_token_usage(10)
        check_token_limit()

    with limit:
        _record_token_usage(11)
        with pytest.raises(SampleLimitExceededError):
            check_token_limit()

    with limit:
        _record_token_usage(10)
        check_token_limit()


def test_can_open_same_context_manager_multiple_times() -> None:
    limit = TokenLimit(10)

    with limit:
        _record_token_usage(10)
        check_token_limit()

        with limit:
            _record_token_usage(10)
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.value == 20


async def test_across_async_contexts():
    async def async_task():
        with model_usage_counter("inner"):
            _record_token_usage(5)

            with TokenLimit(10):
                for _ in range(10):
                    _record_token_usage(1)
                    check_token_limit()
                    # Yield to the event loop to allow other coroutines to run.
                    await asyncio.sleep(0)

    await asyncio.gather(*(async_task() for _ in range(3)))


async def test_same_context_manager_across_async_contexts():
    async def async_task(limit: TokenLimit):
        with model_usage_counter("inner"):
            _record_token_usage(5)

            with limit:
                # Incrementally use 10 tokens (should not exceed the limit).
                for _ in range(10):
                    _record_token_usage(1)
                    check_token_limit()
                    # Yield to the event loop to allow other coroutines to run.
                    await asyncio.sleep(0)

    # The same TokenLimit instance is reused across different async contexts.
    reused_context_manager = TokenLimit(10)
    await asyncio.gather(*(async_task(reused_context_manager) for _ in range(3)))


def test_can_update_limit_value() -> None:
    limit = TokenLimit(10)

    with limit:
        _record_token_usage(5)
        check_token_limit()

        limit.limit = 20
        _record_token_usage(15)
        check_token_limit()

        with pytest.raises(SampleLimitExceededError) as exc_info:
            # Note: the exception is raised as soon as we decrease the limit.
            limit.limit = 10

    assert exc_info.value.value == 20
    assert limit.limit == 10


def test_can_update_limit_value_on_reused_context_manager() -> None:
    shared_limit = TokenLimit(10)

    with shared_limit:
        _record_token_usage(10)
        check_token_limit()

        with shared_limit:
            shared_limit.limit = 20

            _record_token_usage(10)
            check_token_limit()

            _record_token_usage(10)
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.value == 30
