import pytest

from inspect_ai.model._model import sample_model_usage
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._limit import SampleLimitExceededError
from inspect_ai.util._limits import TokenLimit, check_token_limit


@pytest.fixture
def model_usage() -> ModelUsage:
    # Initialize the model usage context var and create an empty fictitious "model"
    # usage object.
    usage_dict = sample_model_usage()
    model_usage = ModelUsage()
    usage_dict["model"] = model_usage
    return model_usage


def test_validates_budget_parameter() -> None:
    with pytest.raises(ValueError):
        TokenLimit(-1)


def test_can_create_with_none_budget() -> None:
    with TokenLimit.create(None):
        check_token_limit()


def test_raises_error_when_limit_exceeded(model_usage: ModelUsage) -> None:
    with TokenLimit(10):
        model_usage.total_tokens = 11
        with pytest.raises(SampleLimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_exceeded_incrementally(
    model_usage: ModelUsage,
) -> None:
    with TokenLimit(10):
        model_usage.total_tokens += 5
        check_token_limit()
        with pytest.raises(SampleLimitExceededError):
            model_usage.total_tokens += 6
            check_token_limit()


def test_does_not_raise_error_when_limit_not_exceeded(model_usage: ModelUsage) -> None:
    model_usage.total_tokens = 10

    with TokenLimit(10):
        model_usage.total_tokens += 10
        check_token_limit()


def test_stack_can_trigger_outer_limit(model_usage: ModelUsage) -> None:
    model_usage.total_tokens = 5

    with TokenLimit(10):
        model_usage.total_tokens += 6
        check_token_limit()

        with TokenLimit(11):
            model_usage.total_tokens += 5
            # Should trigger outer limit (10).
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit(model_usage: ModelUsage) -> None:
    model_usage.total_tokens = 5

    with TokenLimit(10):
        model_usage.total_tokens += 1
        check_token_limit()

        with TokenLimit(5):
            model_usage.total_tokens += 6
            # Should trigger inner limit (5).
            with pytest.raises(SampleLimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked(model_usage: ModelUsage) -> None:
    with TokenLimit(10):
        model_usage.total_tokens += 5
        check_token_limit()

    model_usage.total_tokens += 100
    check_token_limit()


# TODO: Test across different async contexts.
