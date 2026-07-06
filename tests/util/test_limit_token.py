from typing import Generator

import anyio
import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util._async import tg_collect
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._limit import (
    LimitExceededError,
    TokenLimit,
    check_token_limit,
    parse_token_limit,
    record_model_usage,
    resolve_token_limit,
    suspend_token_limit,
    token_limit,
    token_limit_fields,
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
                await anyio.sleep(0)
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_tokens(1)
                assert exc_info.value.value == 11

    # This will result in 3 distinct "trees" each with 1 root node.
    await tg_collect([async_task for _ in range(3)])


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


def test_suspend_token_limit_skips_recording_and_check() -> None:
    with token_limit(10) as limit:
        with suspend_token_limit():
            _consume_tokens(100)
        assert limit.usage == 0


def test_suspend_token_limit_skips_check_with_explicit_check() -> None:
    with token_limit(10):
        with suspend_token_limit():
            record_model_usage(ModelUsage(total_tokens=100))
            check_token_limit()


def test_suspend_token_limit_resumes_metering_on_exit() -> None:
    with token_limit(10) as limit:
        with suspend_token_limit():
            _consume_tokens(100)

        assert limit.usage == 0

        with pytest.raises(LimitExceededError):
            _consume_tokens(11)


def test_suspend_token_limit_with_no_active_limit() -> None:
    with suspend_token_limit():
        _consume_tokens(100)


def test_suspend_token_limit_nested() -> None:
    with token_limit(10) as limit:
        with suspend_token_limit():
            _consume_tokens(50)
            with suspend_token_limit():
                _consume_tokens(50)
            _consume_tokens(50)
        assert limit.usage == 0


def test_suspend_token_limit_hides_inner_token_limit() -> None:
    with token_limit(10) as outer:
        with suspend_token_limit():
            with token_limit(5) as inner:
                _consume_tokens(100)
            assert inner.usage == 0
        assert outer.usage == 0


def test_suspend_token_limit_exception_restores_state() -> None:
    with token_limit(10) as limit:
        with pytest.raises(RuntimeError):
            with suspend_token_limit():
                _consume_tokens(100)
                raise RuntimeError("boom")

        # Metering should be resumed after the suspension exits.
        with pytest.raises(LimitExceededError):
            _consume_tokens(11)

        assert limit.usage == 11


async def test_suspend_token_limit_is_per_task() -> None:
    """Suspension in one async task must not bleed into a sibling task."""

    async def suspended_task() -> int:
        with suspend_token_limit():
            _consume_tokens(100)
            await anyio.sleep(0)
        return 1

    async def metered_task() -> int:
        # Sibling task is not suspended; recording must apply to its own limit.
        with token_limit(10) as limit:
            await anyio.sleep(0)
            _consume_tokens(5)
            assert limit.usage == 5
        return 2

    with token_limit(1000) as outer:
        await tg_collect([suspended_task, metered_task])

    # Only the metered_task's 5 tokens propagate to the outer limit;
    # the suspended_task's 100 are dropped.
    assert outer.usage == 5


def test_output_type_meters_only_output_tokens() -> None:
    with token_limit(10, type="output"):
        # input tokens do not count against an output-type limit
        _consume_usage(input_tokens=100, output_tokens=5)

        with pytest.raises(LimitExceededError) as exc_info:
            _consume_usage(input_tokens=0, output_tokens=6)

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10
    assert exc_info.value.message.startswith("Output token limit exceeded")


def test_output_type_usage_and_remaining() -> None:
    with token_limit(10, type="output") as limit:
        _consume_usage(input_tokens=100, output_tokens=4)

        assert limit.usage == 4
        assert limit.remaining == 6


def test_mixed_type_stacking() -> None:
    with token_limit(100) as outer:
        with token_limit(10, type="output") as inner:
            # 55 total tokens, 5 output tokens
            _consume_usage(input_tokens=50, output_tokens=5)

            assert outer.usage == 55
            assert inner.usage == 5

            with pytest.raises(LimitExceededError) as exc_info:
                # inner output limit (10) trips before outer total limit (100)
                _consume_usage(input_tokens=0, output_tokens=6)

    assert exc_info.value.source is inner


def test_mixed_type_stacking_outer_output_limit() -> None:
    with token_limit(10, type="output") as outer:
        with token_limit(100) as inner:
            with pytest.raises(LimitExceededError) as exc_info:
                # 111 total tokens exceeds inner (100); 11 output tokens exceeds
                # outer (10); the outermost limit raises.
                _consume_usage(input_tokens=100, output_tokens=11)

    assert exc_info.value.source is outer
    assert inner.usage == 111


def test_token_limit_accepts_token_limit_spec() -> None:
    with token_limit(TokenLimit(tokens=10, type="output")) as limit:
        assert limit.limit == 10
        assert limit.type == "output"

        with pytest.raises(LimitExceededError):
            _consume_usage(input_tokens=0, output_tokens=11)


def test_token_limit_rejects_spec_and_type() -> None:
    with pytest.raises(ValueError):
        token_limit(TokenLimit(tokens=10, type="output"), type="output")


def test_token_limit_rejects_invalid_type() -> None:
    with pytest.raises(ValueError):
        token_limit(10, type="outputs")  # type: ignore[arg-type]


def test_token_limit_type_defaults_to_all() -> None:
    with token_limit(10) as limit:
        assert limit.type == "all"

        with pytest.raises(LimitExceededError) as exc_info:
            _consume_usage(input_tokens=6, output_tokens=5)

    assert exc_info.value.message.startswith("Token limit exceeded")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("500000", 500000),
        ("500k", 500_000),
        ("1m", 1_000_000),
        ("1.5m", 1_500_000),
        ("1b", 1_000_000_000),
        ("0", 0),
        ("all:500k", 500_000),
        ("output:1m", TokenLimit(tokens=1_000_000, type="output")),
        ("OUTPUT:1M", TokenLimit(tokens=1_000_000, type="output")),
        ("output: 500 k", TokenLimit(tokens=500_000, type="output")),
    ],
)
def test_parse_token_limit(value: str, expected: int | TokenLimit) -> None:
    assert parse_token_limit(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "abc", "-5", "output:", "1.5", "1.0001k", "output", "5t", "k"],
)
def test_parse_token_limit_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_token_limit(value)


def test_resolve_token_limit() -> None:
    assert resolve_token_limit(None) is None
    assert resolve_token_limit(500) == 500
    assert resolve_token_limit("output:1m") == TokenLimit(
        tokens=1_000_000, type="output"
    )
    # a TokenLimit metering all tokens collapses to a plain int
    assert resolve_token_limit(TokenLimit(tokens=500, type="all")) == 500


def test_token_limit_fields() -> None:
    assert token_limit_fields(None) == (None, None)
    assert token_limit_fields(500) == (500, None)
    assert token_limit_fields("all:1m") == (1_000_000, None)
    assert token_limit_fields("output:1m") == (1_000_000, "output")
    assert token_limit_fields(TokenLimit(tokens=5, type="output")) == (5, "output")
    assert token_limit_fields(TokenLimit(tokens=5, type="all")) == (5, None)


def _consume_tokens(total_tokens: int) -> None:
    record_model_usage(ModelUsage(total_tokens=total_tokens))
    check_token_limit()


def _consume_usage(input_tokens: int, output_tokens: int) -> None:
    record_model_usage(
        ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
    )
    check_token_limit()
