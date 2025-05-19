import pytest

from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._limit import (
    LimitExceededError,
    apply_limits,
    check_message_limit,
    check_token_limit,
    message_limit,
    record_model_usage,
    token_limit,
)


def test_can_use_deprecated_sample_limit_exceeded_error() -> None:
    # SampleLimitExceededError is deprecated in favour of LimitExceededError.
    from inspect_ai.solver import SampleLimitExceededError  # type: ignore

    try:
        with token_limit(1):
            record_model_usage(ModelUsage(total_tokens=10))
            check_token_limit()
        pytest.fail("Expected SampleLimitExceededError")
    except SampleLimitExceededError as exc_info:
        assert exc_info.__class__ == LimitExceededError
        assert exc_info.type == "token"


def test_apply_limits_empty() -> None:
    with apply_limits([]) as limit_scope:
        pass

    assert limit_scope.limit_error is None


def test_apply_limits_catch_errors_true() -> None:
    limit = token_limit(10)
    with apply_limits([limit], catch_errors=True) as limit_scope:
        record_model_usage(ModelUsage(total_tokens=11))
        check_token_limit()

    assert limit_scope.limit_error is not None
    assert limit_scope.limit_error.source is limit


def test_apply_limits_catch_errors_false() -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with apply_limits([token_limit(10)], catch_errors=False) as limit_scope:
            record_model_usage(ModelUsage(total_tokens=11))
            check_token_limit()

    # Despite not catching the error, we still have a reference to it.
    assert limit_scope.limit_error is exc_info.value


def test_apply_limits_not_checked_once_closed() -> None:
    with apply_limits([token_limit(10), message_limit(10)]) as limit_scope:
        pass

    # Check that the limits no longer apply.
    record_model_usage(ModelUsage(total_tokens=11))
    check_token_limit()
    check_message_limit(11, raise_for_equal=False)

    assert limit_scope.limit_error is None


def test_apply_limits_not_exceeded() -> None:
    with apply_limits([token_limit(10)]) as limit_scope:
        pass

    assert limit_scope.limit_error is None


def test_apply_limits_parent_exceeded() -> None:
    with apply_limits([token_limit(10)], catch_errors=True) as parent_scope:
        with apply_limits([token_limit(100)], catch_errors=True) as child_scope:
            record_model_usage(ModelUsage(total_tokens=11))
            check_token_limit()

    assert parent_scope.limit_error is not None
    assert child_scope.limit_error is None


def test_apply_limits_child_exceeded() -> None:
    with apply_limits([token_limit(100)], catch_errors=True) as parent_scope:
        with apply_limits([token_limit(10)], catch_errors=True) as child_scope:
            record_model_usage(ModelUsage(total_tokens=11))
            check_token_limit()

    assert parent_scope.limit_error is None
    assert child_scope.limit_error is not None


def test_apply_limits_handles_error_without_source() -> None:
    with pytest.raises(LimitExceededError):
        with apply_limits([token_limit(10), message_limit(10)]) as limit_scope:
            raise LimitExceededError(type="token", value=11, limit=10)

    assert limit_scope.limit_error is None
