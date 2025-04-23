import asyncio
from typing import Generator

import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._limit import (
    LimitExceededError,
    _TokenLimit,
    check_token_limit,
    record_model_usage,
    token_limit,
)


@pytest.fixture
def model() -> Model:
    """A model which uses one token per generate call."""

    def repeat_forever(output: ModelOutput) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    output = ModelOutput.from_content("mockllm/model", "hello")
    output.usage = ModelUsage(total_tokens=1)
    return get_model("mockllm/model", custom_outputs=repeat_forever(output))


def test_can_record_model_usage_with_no_active_limits() -> None:
    record_model_usage(ModelUsage(total_tokens=1))


def test_can_check_token_limit_with_no_active_limits() -> None:
    check_token_limit()


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        token_limit(-1)


def test_can_create_with_none_limit() -> None:
    with token_limit(None):
        _consume_tokens(10)


def test_can_create_with_zero_limit() -> None:
    with token_limit(0):
        pass


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    _consume_tokens(10)

    with token_limit(10):
        _consume_tokens(10)


def test_raises_error_when_limit_exceeded() -> None:
    with token_limit(10):
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_tokens(11)

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_repeatedly_exceeded() -> None:
    with token_limit(10):
        with pytest.raises(LimitExceededError):
            _consume_tokens(11)
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_tokens(1)

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 12
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    with token_limit(10):
        _consume_tokens(5)
        with pytest.raises(LimitExceededError):
            _consume_tokens(6)


def test_stack_can_trigger_outer_limit() -> None:
    _consume_tokens(5)

    with token_limit(10):
        _consume_tokens(6)

        with token_limit(11):
            with pytest.raises(LimitExceededError) as exc_info:
                # Should trigger outer limit (10).
                _consume_tokens(5)

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit() -> None:
    _consume_tokens(5)

    with token_limit(10):
        _consume_tokens(1)

        with token_limit(5):
            with pytest.raises(LimitExceededError) as exc_info:
                # Should trigger inner limit (5).
                _consume_tokens(6)

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked() -> None:
    with token_limit(10):
        _consume_tokens(5)

    _consume_tokens(100)


def test_outer_limit_is_checked_after_inner_limit_popped() -> None:
    _consume_tokens(5)

    with token_limit(10):
        _consume_tokens(5)

        with token_limit(5):
            _consume_tokens(1)

        with pytest.raises(LimitExceededError) as exc_info:
            # Should trigger outer limit (10).
            _consume_tokens(5)

    assert exc_info.value.limit == 10
    assert exc_info.value.value == 11


def test_can_reuse_context_manager() -> None:
    limit = token_limit(10)

    with limit:
        _consume_tokens(10)

    with limit:
        _consume_tokens(10)

    with limit:
        with pytest.raises(LimitExceededError):
            _consume_tokens(11)

    with limit:
        _consume_tokens(10)


def test_can_reuse_context_manager_in_stack() -> None:
    limit = token_limit(10)

    with limit:
        _consume_tokens(10)

        with limit:
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_tokens(10)

    assert exc_info.value.value == 20


async def test_same_context_manager_across_async_contexts():
    async def async_task(limit: _TokenLimit):
        _consume_tokens(5)

        with limit:
            # Incrementally use 10 tokens (should not exceed the limit).
            for _ in range(10):
                _consume_tokens(1)
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_tokens(1)
                assert exc_info.value.value == 11

    # The same TokenLimit instance is reused across different async contexts.
    reused_context_manager = token_limit(10)
    # This will result in 3 distinct "trees" each with 1 root node.
    await asyncio.gather(*(async_task(reused_context_manager) for _ in range(3)))


def test_can_update_limit_value() -> None:
    limit = token_limit(10)

    with limit:
        _consume_tokens(5)

        limit.limit = 20
        _consume_tokens(15)

        limit.limit = 10

        with pytest.raises(LimitExceededError) as exc_info:
            check_token_limit()
            assert exc_info.value.value == 20

        limit.limit = None
        _consume_tokens(5)

    assert limit.limit is None


def test_can_update_limit_value_on_reused_context_manager() -> None:
    shared_limit = token_limit(10)

    with shared_limit:
        _consume_tokens(10)

        with shared_limit:
            shared_limit.limit = 20

            _consume_tokens(10)

            with pytest.raises(LimitExceededError) as exc_info:
                # Should trigger the outer limit (20).
                _consume_tokens(10)

    assert exc_info.value.value == 30
    assert exc_info.value.limit == 20


def test_parallel_nested_forks(model: Model):
    """An eval which has 2 levels of forking."""

    @solver
    def forking_solver():
        async def solve(state: TaskState, generate: Generate):
            """Consumes 26 tokens: 2 itself, 24 for the forks."""
            with token_limit(25):
                await model.generate("")

                # Consumes 24 tokens.
                await fork(state, [outer_fork() for _ in range(3)])

                with pytest.raises(LimitExceededError) as exc_info:
                    # Consuming the 26th token exceeds the limit.
                    await model.generate("")
                    assert exc_info.value.value == 26

            return state

        return solve

    @solver
    def outer_fork():
        async def solve(state: TaskState, generate: Generate):
            """Consumes 8 tokens: 2 itself and 6 for the inner forks."""
            with token_limit(7):
                await model.generate("")

                # Consumes 6 tokens.
                await fork(state, [inner_fork() for _ in range(3)])

                with pytest.raises(LimitExceededError) as exc_info:
                    # Consuming the 8th token exceeds the limit.
                    await model.generate("")
                    assert exc_info.value.value == 8

            return state

        return solve

    @solver
    def inner_fork():
        async def solve(state: TaskState, generate: Generate):
            """Consumes 2 tokens."""
            with token_limit(1):
                await model.generate("")

                with pytest.raises(LimitExceededError) as exc_info:
                    # Consuming the 2nd token exceeds the limit.
                    await model.generate("")
                    assert exc_info.value.value == 2

            return state

        return solve

    result = eval(Task(solver=forking_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 26


def _consume_tokens(total_tokens: int) -> None:
    record_model_usage(ModelUsage(total_tokens=total_tokens))
    check_token_limit()
