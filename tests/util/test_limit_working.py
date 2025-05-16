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


def test_can_record_waiting_time_with_no_active_limits() -> None:
    record_waiting_time(10)


def test_can_check_token_limit_with_no_active_limits() -> None:
    check_working_limit()


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        working_limit(-1)


def test_can_create_with_none_limit(mock_time: _MockTime) -> None:
    with working_limit(None):
        mock_time.advance(10)
        check_working_limit()


def test_can_create_with_zero_limit() -> None:
    with working_limit(0):
        pass


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    with working_limit(10):
        check_working_limit()


def test_raises_error_when_limit_exceeded(mock_time: _MockTime) -> None:
    with working_limit(1):
        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(5)
            check_working_limit()

    assert exc_info.value.type == "working"
    assert exc_info.value.value == 5
    assert exc_info.value.limit == 1


def test_raises_error_when_limit_repeatedly_exceeded(
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


def test_stack_can_trigger_outer_limit(mock_time: _MockTime) -> None:
    with working_limit(1):
        with working_limit(10):
            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(2)
                check_working_limit()

    assert exc_info.value.limit == 1


def test_stack_can_trigger_inner_limit(mock_time: _MockTime) -> None:
    with working_limit(10):
        with working_limit(1):
            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(2)
                check_working_limit()

    assert exc_info.value.limit == 1


def test_outer_limit_is_checked_after_inner_limit_popped(mock_time: _MockTime) -> None:
    with working_limit(1):
        with working_limit(10):
            pass

        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(2)
            check_working_limit()

    assert exc_info.value.limit == 1
    assert exc_info.value.value == 2


def test_out_of_scope_limits_are_not_checked(mock_time: _MockTime) -> None:
    with working_limit(1):
        pass

    mock_time.advance(2)
    check_working_limit()


def test_subtracts_waiting_time(mock_time: _MockTime) -> None:
    with working_limit(1):
        mock_time.advance(2)
        record_waiting_time(2)
        check_working_limit()

        mock_time.advance(10)
        with pytest.raises(LimitExceededError) as exc_info:
            check_working_limit()

    assert exc_info.value.value == 10


def test_subtracts_waiting_time_from_ancestors(mock_time: _MockTime) -> None:
    with working_limit(2):
        with working_limit(10):
            mock_time.advance(3)
            record_waiting_time(1)
            check_working_limit()

            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(1)
                check_working_limit()

    assert exc_info.value.value == 3


class _MockTime:
    def __init__(self) -> None:
        self._current_time = 0.0

    def get_time(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> float:
        self._current_time += seconds
        return self._current_time
