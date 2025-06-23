from __future__ import annotations

from typing import Generator
from unittest.mock import patch

import pytest

from inspect_ai.util._limit import (
    LimitExceededError,
    check_working_limit,
    record_waiting_time,
    working_limit,
)


@pytest.fixture
def mock_time() -> Generator[_MockTime, None, None]:
    mock = _MockTime()
    with patch("time.monotonic", side_effect=mock.get_time):
        yield mock


async def test_can_record_waiting_time_with_no_active_limits() -> None:
    record_waiting_time(10)


async def test_can_check_token_limit_with_no_active_limits() -> None:
    check_working_limit()


async def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        working_limit(-1)


async def test_can_create_with_none_limit(mock_time: _MockTime) -> None:
    with working_limit(None):
        mock_time.advance(10)
        check_working_limit()


async def test_can_create_with_zero_limit() -> None:
    with working_limit(0):
        pass


async def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    with working_limit(10):
        check_working_limit()


async def test_raises_error_when_limit_exceeded(mock_time: _MockTime) -> None:
    with working_limit(1) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(5)
            check_working_limit()

    assert exc_info.value.type == "working"
    assert exc_info.value.value == 5
    assert exc_info.value.limit == 1
    assert exc_info.value.source is limit


async def test_raises_error_when_limit_repeatedly_exceeded(
    mock_time: _MockTime,
) -> None:
    with working_limit(1):
        with pytest.raises(LimitExceededError):
            mock_time.advance(2)
            check_working_limit()
        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(1)
            check_working_limit()

    assert exc_info.value.value == 3
    assert exc_info.value.limit == 1


async def test_stack_can_trigger_outer_limit(mock_time: _MockTime) -> None:
    with working_limit(1):
        with working_limit(10):
            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(2)
                check_working_limit()

    assert exc_info.value.limit == 1


async def test_stack_can_trigger_inner_limit(mock_time: _MockTime) -> None:
    with working_limit(10):
        with working_limit(1):
            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(2)
                check_working_limit()

    assert exc_info.value.limit == 1


async def test_outer_limit_is_checked_after_inner_limit_popped(
    mock_time: _MockTime,
) -> None:
    with working_limit(1):
        with working_limit(10):
            pass

        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(2)
            check_working_limit()

    assert exc_info.value.limit == 1
    assert exc_info.value.value == 2


async def test_out_of_scope_limits_are_not_checked(mock_time: _MockTime) -> None:
    with working_limit(1):
        pass

    mock_time.advance(2)
    check_working_limit()


async def test_subtracts_waiting_time(mock_time: _MockTime) -> None:
    with working_limit(1):
        mock_time.advance(2)
        record_waiting_time(2)
        check_working_limit()

        mock_time.advance(10)
        with pytest.raises(LimitExceededError) as exc_info:
            check_working_limit()

    assert exc_info.value.value == 10


async def test_subtracts_waiting_time_from_ancestors(mock_time: _MockTime) -> None:
    with working_limit(2):
        with working_limit(10):
            mock_time.advance(3)
            record_waiting_time(1)
            check_working_limit()

            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(1)
                check_working_limit()

    assert exc_info.value.value == 3


async def test_outermost_limit_raises_error_when_multiple_limits_exceeded(
    mock_time: _MockTime,
) -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with working_limit(1) as outer:
            with working_limit(2):
                mock_time.advance(10)
                check_working_limit()

    # The outermost limit is the one that the error is raised against, despite both
    # limits being exceeded.
    # This prevents sub-agent architectures (e.g. one that dispatches a new sub-agent
    # each time a sub-agent reaches a working limit) from getting stuck in an infinite
    # loop.
    assert exc_info.value.limit == 1
    assert exc_info.value.source is outer


def test_can_get_limit_value() -> None:
    limit = working_limit(10)

    assert limit.limit == 10


async def test_can_get_usage_while_context_manager_open(mock_time: _MockTime) -> None:
    with working_limit(10) as limit:
        mock_time.advance(3)
        record_waiting_time(1)

        assert limit.usage == 2


async def test_can_get_usage_before_context_manager_opened(
    mock_time: _MockTime,
) -> None:
    limit = working_limit(10)
    mock_time.advance(3)
    record_waiting_time(1)

    assert limit.usage == 0


async def test_can_get_usage_after_context_manager_closed(mock_time: _MockTime) -> None:
    with working_limit(10) as limit:
        mock_time.advance(3)
        record_waiting_time(1)

    mock_time.advance(10)

    assert limit.usage == 2


async def test_can_get_usage_nested(mock_time: _MockTime) -> None:
    with working_limit(10) as outer_limit:
        mock_time.advance(3)
        with working_limit(10) as inner_limit:
            mock_time.advance(3)

    assert outer_limit.usage == 6
    assert inner_limit.usage == 3


async def test_can_get_usage_after_limit_error(mock_time: _MockTime) -> None:
    with pytest.raises(LimitExceededError):
        with working_limit(1) as limit:
            mock_time.advance(10)
            record_waiting_time(1)
            check_working_limit()

    assert limit.usage == 9


async def test_can_get_remaining(mock_time: _MockTime) -> None:
    limit = working_limit(10)
    with limit:
        mock_time.advance(4)

        assert limit.remaining is not None
        assert limit.remaining == 6


async def test_cannot_reuse_context_manager() -> None:
    limit = working_limit(10)
    with limit:
        pass

    with pytest.raises(RuntimeError) as exc_info:
        # Reusing the same Limit instance.
        with limit:
            pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


async def test_cannot_reuse_context_manager_in_stack() -> None:
    limit = working_limit(10)

    with pytest.raises(RuntimeError) as exc_info:
        with limit:
            # Reusing the same Limit instance in a stack.
            with limit:
                pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


class _MockTime:
    def __init__(self) -> None:
        self._current_time = 0.0

    def get_time(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> float:
        self._current_time += seconds
        return self._current_time
