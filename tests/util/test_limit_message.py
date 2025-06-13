import asyncio

import pytest

from inspect_ai.util._limit import (
    LimitExceededError,
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
    with message_limit(10) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            check_message_limit(11, raise_for_equal=False)

    assert exc_info.value.type == "message"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10
    assert exc_info.value.source is limit


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


def test_can_get_limit_value() -> None:
    limit = message_limit(10)

    assert limit.limit == 10


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


def test_get_usage_raises_error() -> None:
    with message_limit(10) as limit:
        with pytest.raises(NotImplementedError) as exc_info:
            _ = limit.usage

    assert "is not supported" in str(exc_info.value), str(exc_info.value)


def test_get_remaining_raises_error() -> None:
    limit = message_limit(10)

    with pytest.raises(NotImplementedError) as exc_info:
        _ = limit.remaining

    assert "is not supported" in str(exc_info.value), str(exc_info.value)


def test_cannot_reuse_context_manager() -> None:
    limit = message_limit(10)
    with limit:
        pass

    with pytest.raises(RuntimeError) as exc_info:
        # Reusing the same Limit instance.
        with limit:
            pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


def test_cannot_reuse_context_manager_in_stack() -> None:
    limit = message_limit(10)

    with pytest.raises(RuntimeError) as exc_info:
        with limit:
            # Reusing the same Limit instance in a stack.
            with limit:
                pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


async def test_limits_across_async_contexts():
    async def async_task():
        with message_limit(10):
            # Incrementally increase conversation length (should not exceed the limit).
            for i in range(11):
                check_message_limit(i, raise_for_equal=False)
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)
            with pytest.raises(LimitExceededError) as exc_info:
                check_message_limit(11, raise_for_equal=False)
                assert exc_info.value.value == 11

    # This will result in 3 distinct "trees" each with 1 root node.
    await asyncio.gather(*(async_task() for _ in range(3)))
