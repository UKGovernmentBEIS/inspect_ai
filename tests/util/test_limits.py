import pytest

from inspect_ai.model._model import sample_model_usage
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError
from inspect_ai.util._limits import TokenLimitCtx, check_token_limit


def test_validates_budget() -> None:
    with pytest.raises(ValueError):
        TokenLimitCtx(-1)


def test_raises_error_when_limit_exceeded() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage()

    with TokenLimitCtx(10):
        usage_dict["model"].total_tokens = 11
        with pytest.raises(SampleLimitExceededError):
            check_token_limit()


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage()

    with TokenLimitCtx(10):
        usage_dict["model"].total_tokens += 8
        check_token_limit()
        with pytest.raises(SampleLimitExceededError):
            usage_dict["model"].total_tokens += 8
            check_token_limit()


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage()

    with TokenLimitCtx(10):
        usage_dict["model"].total_tokens = 10
        check_token_limit()


def test_stack_can_trigger_outer_limit() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage(total_tokens=8)

    with TokenLimitCtx(10):
        usage_dict["model"].total_tokens += 8
        check_token_limit()

        with TokenLimitCtx(11):
            usage_dict["model"].total_tokens += 8
            # Should trigger outer limit.
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage(total_tokens=8)

    with TokenLimitCtx(10):
        usage_dict["model"].total_tokens += 1
        check_token_limit()

        with TokenLimitCtx(5):
            usage_dict["model"].total_tokens += 6
            # Should trigger outer limit.
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 5
