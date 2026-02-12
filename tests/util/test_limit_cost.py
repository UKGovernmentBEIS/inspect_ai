import pytest

from inspect_ai.util._limit import (
    LimitExceededError,
    check_cost_limit,
    cost_limit,
    record_model_cost,
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


def _consume_cost(amount: float) -> None:
    record_model_cost(amount)
    check_cost_limit()
