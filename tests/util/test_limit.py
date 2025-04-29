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
    with apply_limits([]):
        pass


def test_apply_limits() -> None:
    with apply_limits([token_limit(10), message_limit(10)]):
        with pytest.raises(LimitExceededError):
            record_model_usage(ModelUsage(total_tokens=11))
            check_token_limit()
        with pytest.raises(LimitExceededError):
            check_message_limit(11, raise_for_equal=False)

    record_model_usage(ModelUsage(total_tokens=11))
    check_token_limit()
    check_message_limit(11, raise_for_equal=False)
