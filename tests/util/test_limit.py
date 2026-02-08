import asyncio

import pytest

from inspect_ai._eval.eval import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.dataset._dataset import Sample
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._limit import (
    LimitExceededError,
    apply_limits,
    check_message_limit,
    check_token_limit,
    message_limit,
    record_model_usage,
    sample_limits,
    time_limit,
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


@pytest.mark.parametrize(
    "value, expected",
    [
        # ints do not have decimal places
        (1, "1"),
        # floats have 2 decimal places
        (1.2345, "1.23"),
        # Thousand separators for both ints and floats
        (200_000, "200,000"),
        (200_000.0, "200,000.00"),
        # Negative numbers
        (-3, "-3"),
        (-3.4567, "-3.46"),
    ],
)
def test_limit_exceeded_error_string_format(value: int | float, expected: str) -> None:
    error = LimitExceededError(type="token", value=value, limit=value)

    assert error.limit_str == expected
    assert error.value_str == expected


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


@pytest.mark.anyio
async def test_apply_limits_handles_time_limit() -> None:
    # Verifying that apply_limits() catches LimitExceededError even when it is raised
    # by the closing of its ExitStack.
    # Unlike other limits, the time_limit() uses anyio to cancel the scope within the
    # context manager, meaning the LimitExceededError is only raised when exiting the
    # limit context manager (as a result of a CancelledError).
    with apply_limits([time_limit(0.1)], catch_errors=True) as limit_scope:
        await asyncio.sleep(0.5)

    assert limit_scope.limit_error is not None


def test_get_sample_limits_when_no_sample_running() -> None:
    with pytest.raises(RuntimeError):
        sample_limits()


def test_get_sample_limits_within_eval() -> None:
    @solver
    def test_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            record_model_usage(ModelUsage(total_tokens=40))
            limits = sample_limits()
            assert limits.message.limit == 10
            assert limits.token.limit == 100
            assert limits.token.remaining == 60
            assert limits.token.usage == 40
            assert limits.time.limit == 1_000
            assert limits.time.usage > 0
            assert limits.working.limit == 10_000
            assert limits.working.usage > 0
            assert limits.cost.limit is None

            # Verify that we still get the sample level limits when a scoped limit is active
            with token_limit(1):
                assert sample_limits().token.limit == 100

            return state

        return solve

    task = Task(
        dataset=[Sample(input="Say Hello")],
        solver=test_solver(),
        message_limit=10,
        token_limit=100,
        time_limit=1_000,
        working_limit=10_000,
    )

    log = eval(task, model="mockllm/model")[0]

    # Assertion failures in the solver will manifest as a failed eval.
    assert log.status == "success"
