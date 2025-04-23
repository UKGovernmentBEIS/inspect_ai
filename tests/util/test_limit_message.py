import asyncio

import pytest

from inspect_ai.util._limit import (
    LimitExceededError,
    _MessageLimit,
    check_message_limit,
    message_limit,
)


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        message_limit(-1)


def test_can_create_with_none_limit() -> None:
    with message_limit(None):
        check_message_limit(10, raise_for_equal=False)


def test_can_create_with_zero_limit() -> None:
    with message_limit(0):
        pass


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    with message_limit(10):
        check_message_limit(10, raise_for_equal=False)


def test_raises_error_when_limit_exceeded() -> None:
    with message_limit(10):
        with pytest.raises(LimitExceededError) as exc_info:
            check_message_limit(11, raise_for_equal=False)

    assert exc_info.value.type == "message"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_equal_and_check_equal_true() -> None:
    with message_limit(10):
        with pytest.raises(LimitExceededError) as exc_info:
            check_message_limit(10, raise_for_equal=True)

    assert exc_info.value.type == "message"
    assert exc_info.value.value == 10
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_repeatedly_exceeded() -> None:
    with message_limit(10):
        with pytest.raises(LimitExceededError):
            check_message_limit(11, raise_for_equal=False)
        with pytest.raises(LimitExceededError) as exc_info:
            check_message_limit(12, raise_for_equal=False)

    assert exc_info.value.type == "message"
    assert exc_info.value.value == 12
    assert exc_info.value.limit == 10


def test_out_of_scope_limits_are_not_checked() -> None:
    with message_limit(10):
        check_message_limit(10, raise_for_equal=False)

    check_message_limit(11, raise_for_equal=False)


def test_ancestor_limits_are_not_checked() -> None:
    with message_limit(10):
        with message_limit(100):
            check_message_limit(50, raise_for_equal=False)
        check_message_limit(5, raise_for_equal=False)


def test_ancestor_limits_are_restored() -> None:
    with message_limit(10):
        with message_limit(100):
            pass
        with pytest.raises(LimitExceededError) as exc_info:
            check_message_limit(11, raise_for_equal=False)

    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_can_reuse_context_manager() -> None:
    limit = message_limit(10)

    with limit:
        check_message_limit(10, raise_for_equal=False)

    with limit:
        check_message_limit(10, raise_for_equal=False)

    with limit:
        with pytest.raises(LimitExceededError):
            check_message_limit(11, raise_for_equal=False)

    with limit:
        check_message_limit(10, raise_for_equal=False)


def test_can_reuse_context_manager_in_stack() -> None:
    limit = message_limit(10)

    with limit:
        check_message_limit(10, raise_for_equal=False)

        with limit:
            with pytest.raises(LimitExceededError) as exc_info:
                check_message_limit(20, raise_for_equal=False)

    assert exc_info.value.value == 20


def test_can_update_limit_value() -> None:
    limit = message_limit(20)

    with limit:
        limit.limit = 10
        with pytest.raises(LimitExceededError) as exc_info:
            check_message_limit(15, raise_for_equal=False)

        assert exc_info.value.value == 15
        assert exc_info.value.limit == 10

        limit.limit = None
        check_message_limit(100, raise_for_equal=False)

    assert limit.limit is None


async def test_same_context_manager_across_async_contexts():
    async def async_task(limit: _MessageLimit):
        with limit:
            # Incrementally increase conversation length (should not exceed the limit).
            for i in range(11):
                check_message_limit(i, raise_for_equal=False)
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)
            with pytest.raises(LimitExceededError) as exc_info:
                check_message_limit(11, raise_for_equal=False)
                assert exc_info.value.value == 11

    # The same MessageLimit instance is reused across different async contexts.
    reused_context_manager = message_limit(10)
    # This will result in 3 distinct "trees" each with 1 root node.
    await asyncio.gather(*(async_task(reused_context_manager) for _ in range(3)))
