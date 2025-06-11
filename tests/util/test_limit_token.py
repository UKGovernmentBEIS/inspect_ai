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
    with token_limit(10) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_tokens(11)

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10
    assert exc_info.value.source is limit


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


def test_outermost_limit_raises_error_when_multiple_limits_exceeded() -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with token_limit(1) as outer:
            with token_limit(2):
                _consume_tokens(10)

    # The outermost limit is the one that the error is raised against, despite both
    # limits being exceeded.
    # This prevents sub-agent architectures (e.g. one that dispatches a new sub-agent
    # each time a sub-agent reaches a token limit) from getting stuck in an infinite
    # loop.
    assert exc_info.value.limit == 1
    assert exc_info.value.source is outer


def test_can_get_limit_value() -> None:
    limit = token_limit(10)

    assert limit.limit == 10


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


def test_can_get_usage_while_context_manager_open() -> None:
    with token_limit(10) as limit:
        _consume_tokens(5)

        assert limit.usage == 5


def test_can_get_usage_before_context_manager_opened() -> None:
    limit = token_limit(10)

    assert limit.usage == 0


def test_can_get_usage_after_context_manager_closed() -> None:
    with token_limit(10) as limit:
        _consume_tokens(5)

    assert limit.usage == 5


def test_can_get_usage_nested() -> None:
    with token_limit(10) as limit_outer:
        _consume_tokens(5)
        with token_limit(10) as limit_inner:
            _consume_tokens(5)

    assert limit_outer.usage == 10
    assert limit_inner.usage == 5


def test_can_get_usage_after_limit_error() -> None:
    with pytest.raises(LimitExceededError):
        with token_limit(10) as limit:
            _consume_tokens(15)

    assert limit.usage == 15


async def test_can_get_remaining() -> None:
    limit = token_limit(10)
    with limit:
        _consume_tokens(4)

        assert limit.remaining is not None
        assert limit.remaining == 6


def test_cannot_reuse_context_manager() -> None:
    limit = token_limit(10)
    with limit:
        pass

    with pytest.raises(RuntimeError) as exc_info:
        # Reusing the same Limit instance.
        with limit:
            pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


def test_cannot_reuse_context_manager_in_stack() -> None:
    limit = token_limit(10)

    with pytest.raises(RuntimeError) as exc_info:
        with limit:
            # Reusing the same Limit instance in a stack.
            with limit:
                pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


async def test_same_context_manager_across_async_contexts():
    async def async_task():
        _consume_tokens(5)

        with token_limit(10):
            # Incrementally use 10 tokens (should not exceed the limit).
            for _ in range(10):
                _consume_tokens(1)
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_tokens(1)
                assert exc_info.value.value == 11

    # This will result in 3 distinct "trees" each with 1 root node.
    await asyncio.gather(*(async_task() for _ in range(3)))


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
