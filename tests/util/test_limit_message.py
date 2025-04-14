import pytest

from inspect_ai.util._limit import LimitExceededError, message_limit


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        message_limit(-1)


def test_can_create_with_none_limit() -> None:
    message_limit(None)


def test_can_create_with_zero_limit() -> None:
    message_limit(0)


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    limit = message_limit(10)

    limit.check(10, raise_for_equal=False)


def test_raises_error_when_limit_exceeded() -> None:
    limit = message_limit(10)

    with pytest.raises(LimitExceededError) as exc_info:
        limit.check(11, raise_for_equal=False)

    assert exc_info.value.type == "message"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_equal_and_check_equal_true() -> None:
    limit = message_limit(10)

    with pytest.raises(LimitExceededError) as exc_info:
        limit.check(10, raise_for_equal=True)

    assert exc_info.value.type == "message"
    assert exc_info.value.value == 10
    assert exc_info.value.limit == 10


def test_can_modify_limit() -> None:
    limit = message_limit(20)

    limit.limit = 10
    with pytest.raises(LimitExceededError) as exc_info:
        limit.check(15, raise_for_equal=False)

    assert exc_info.value.value == 15
    assert exc_info.value.limit == 10

    limit.limit = None
    limit.check(100, raise_for_equal=False)


def test_raises_error_when_limit_repeatedly_exceeded() -> None:
    limit = message_limit(10)

    with pytest.raises(LimitExceededError):
        limit.check(11, raise_for_equal=False)

    with pytest.raises(LimitExceededError):
        limit.check(11, raise_for_equal=False)


# TODO:
# - tests across async contexts?
