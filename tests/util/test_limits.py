import pytest

from inspect_ai.model._model import sample_model_usage
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError
from inspect_ai.util._limits import TokenLimit, check_token_limit


def test_validates_budget() -> None:
    with pytest.raises(ValueError):
        TokenLimit(-1)


def test_raises_error_when_limit_exceeded() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage()

    with TokenLimit(10):
        usage_dict["model"].total_tokens = 11
        with pytest.raises(SampleLimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage()

    with TokenLimit(10):
        usage_dict["model"].total_tokens += 8
        check_token_limit()
        with pytest.raises(SampleLimitExceededError):
            usage_dict["model"].total_tokens += 8
            check_token_limit()


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage(total_tokens=10)

    with TokenLimit(10):
        usage_dict["model"].total_tokens += 10
        check_token_limit()


def test_stack_can_trigger_outer_limit() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage(total_tokens=8)

    with TokenLimit(10):
        usage_dict["model"].total_tokens += 8
        check_token_limit()

        with TokenLimit(11):
            usage_dict["model"].total_tokens += 8
            # Should trigger outer limit.
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage(total_tokens=8)

    with TokenLimit(10):
        usage_dict["model"].total_tokens += 1
        check_token_limit()

        with TokenLimit(5):
            usage_dict["model"].total_tokens += 6
            # Should trigger inner limit.
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked() -> None:
    usage_dict = sample_model_usage()
    usage_dict["model"] = ModelUsage()

    with TokenLimit(10):
        usage_dict["model"].total_tokens += 5
        check_token_limit()

    usage_dict["model"].total_tokens += 100
    check_token_limit()


# TODO: Test across different async contexts.
