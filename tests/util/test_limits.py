import asyncio
from typing import Generator

import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import run
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver._fork import fork
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import _limit
from inspect_ai.util._limit import (
    LimitExceededError,
    TokenLimit,
    check_token_limit,
    record_model_usage,
    token_limit,
)
from inspect_ai.util._subtask import subtask


@pytest.fixture
def model() -> Model:
    """A model which uses one token per generate call."""

    def repeat_forever(output: ModelOutput) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    return get_model(
        "mockllm/model",
        custom_outputs=repeat_forever(ModelOutput(usage=ModelUsage(total_tokens=1))),
    )


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        TokenLimit(-1)


def test_can_create_with_none_limit() -> None:
    with TokenLimit(None):
        check_token_limit()


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    _record_token_usage(10)

    with TokenLimit(10):
        # TODO: Combine check_token_limit and _record_token_usage?
        _record_token_usage(10)
        check_token_limit()


def test_raises_error_when_limit_exceeded() -> None:
    with TokenLimit(10):
        _record_token_usage(11)
        with pytest.raises(LimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_repeatedly_exceeded() -> None:
    with TokenLimit(10):
        _record_token_usage(11)
        with pytest.raises(LimitExceededError):
            check_token_limit()
        _record_token_usage(1)
        with pytest.raises(LimitExceededError) as exc_info:
            check_token_limit()

    assert exc_info.value.type == "token"
    assert exc_info.value.value == 12
    assert exc_info.value.limit == 10


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    with TokenLimit(10):
        _record_token_usage(5)
        check_token_limit()
        with pytest.raises(LimitExceededError):
            _record_token_usage(6)
            check_token_limit()


def test_stack_can_trigger_outer_limit() -> None:
    _record_token_usage(5)

    with TokenLimit(10):
        _record_token_usage(6)
        check_token_limit()

        with TokenLimit(11):
            _record_token_usage(5)
            # Should trigger outer limit (10).
            with pytest.raises(LimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit() -> None:
    _record_token_usage(5)

    with TokenLimit(10):
        _record_token_usage(1)
        check_token_limit()

        with TokenLimit(5):
            _record_token_usage(6)
            with pytest.raises(LimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked() -> None:
    with TokenLimit(10):
        _record_token_usage(5)
        check_token_limit()

    _record_token_usage(100)
    check_token_limit()


def test_can_reuse_context_manager() -> None:
    limit = TokenLimit(10)

    with limit:
        _record_token_usage(10)
        check_token_limit()

    with limit:
        _record_token_usage(10)
        check_token_limit()

    with limit:
        _record_token_usage(11)
        with pytest.raises(LimitExceededError):
            check_token_limit()

    with limit:
        _record_token_usage(10)
        check_token_limit()


def test_can_open_same_context_manager_multiple_times() -> None:
    limit = TokenLimit(10)

    with limit:
        _record_token_usage(10)
        check_token_limit()

        with limit:
            _record_token_usage(10)
            with pytest.raises(LimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.value == 20


async def test_across_async_contexts():
    async def async_task():
        _record_token_usage(5)

        with TokenLimit(10):
            for _ in range(10):
                _record_token_usage(1)
                check_token_limit()
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)

    await asyncio.gather(*(async_task() for _ in range(3)))


async def test_same_context_manager_across_async_contexts():
    async def async_task(limit: TokenLimit):
        _record_token_usage(5)

        with limit:
            # Incrementally use 10 tokens (should not exceed the limit).
            for _ in range(10):
                _record_token_usage(1)
                check_token_limit()
                # Yield to the event loop to allow other coroutines to run.
                await asyncio.sleep(0)

    # The same TokenLimit instance is reused across different async contexts.
    reused_context_manager = TokenLimit(10)
    await asyncio.gather(*(async_task(reused_context_manager) for _ in range(3)))


def test_can_update_limit_value() -> None:
    limit = TokenLimit(10)

    with limit:
        _record_token_usage(5)
        check_token_limit()

        limit.limit = 20
        _record_token_usage(15)
        check_token_limit()

        with pytest.raises(LimitExceededError) as exc_info:
            # Note: the exception is raised as soon as we decrease the limit.
            limit.limit = 10

    assert exc_info.value.value == 20
    assert limit.limit == 10


def test_can_update_limit_value_on_reused_context_manager() -> None:
    shared_limit = TokenLimit(10)

    with shared_limit:
        _record_token_usage(10)
        check_token_limit()

        with shared_limit:
            shared_limit.limit = 20

            _record_token_usage(10)
            check_token_limit()

            _record_token_usage(10)
            with pytest.raises(LimitExceededError) as exc_info:
                check_token_limit()

    assert exc_info.value.value == 30


def test_parallel_subtasks(model: Model) -> None:
    @solver
    def subtask_solver():
        async def solve(state: TaskState, generate: Generate):
            with token_limit(5):
                assert _get_token_count() == 0

                await model.generate("")
                assert _get_token_count() == 1

                subtasks = [my_subtask() for _ in range(3)]
                await asyncio.gather(*subtasks)
                assert _get_token_count() == 4

                await model.generate("")
                assert _get_token_count() == 5

                with pytest.raises(LimitExceededError):
                    await model.generate("")

            return state

        return solve

    @subtask
    async def my_subtask() -> str:
        """Consumes 1 token."""
        with token_limit(1):
            assert _get_token_count() == 0

            await model.generate("")
            assert _get_token_count() == 1

            return ""

    result = eval(Task(solver=subtask_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 5


def test_nested_subtasks(model: Model) -> None:
    @solver
    def nested_subtask_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _get_token_count() == 0

            await model.generate("")
            assert _get_token_count() == 1

            subtasks = [outer_subtask() for _ in range(3)]
            await asyncio.gather(*subtasks)
            assert _get_token_count() == 16

            await model.generate("")
            assert _get_token_count() == 17

            return state

        return solve

    @subtask
    async def outer_subtask() -> str:
        """Consumes 2 tokens itself, and 1 for each of the 3 inner subtasks."""
        with token_limit(5):
            assert _get_token_count() == 0

            await model.generate("")
            assert _get_token_count() == 1

            inner_subtasks = [inner_subtask() for _ in range(3)]
            await asyncio.gather(*inner_subtasks)

            await model.generate("")
            assert _get_token_count() == 5

            return ""

    @subtask
    async def inner_subtask() -> str:
        """Consumes 1 token."""
        with token_limit(1):
            assert _get_token_count() == 0

            await model.generate("")
            assert _get_token_count() == 1

            return ""

    eval(Task(solver=nested_subtask_solver()))


def test_parallel_forks(model: Model):
    @solver
    def forking_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _get_token_count() == 0

            await model.generate("")
            assert _get_token_count() == 1

            await fork(state, [forked_solver() for _ in range(3)])
            assert _get_token_count() == 4

            await model.generate("")
            assert _get_token_count() == 5

            return state

        return solve

    @solver
    def forked_solver():
        async def solve(state: TaskState, generate: Generate):
            """Consumes 1 token."""
            with token_limit(1):
                assert _get_token_count() == 0

                await model.generate("")
                assert _get_token_count() == 1

            return state

        return solve

    result = eval(Task(solver=forking_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 5


def test_parallel_agents(model: Model) -> None:
    @solver
    def agent_solver():
        async def solve(state: TaskState, generate: Generate):
            assert _get_token_count() == 0

            await model.generate("")
            assert _get_token_count() == 1

            await asyncio.gather(*[run(my_agent(), "") for _ in range(3)])
            assert _get_token_count() == 4

            await model.generate("")
            assert _get_token_count() == 5

            return state

        return solve

    @agent
    def my_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            """Consumes 1 token."""
            with token_limit(1):
                assert _get_token_count() == 0

                await model.generate("")
                assert _get_token_count() == 1

                return state

        return execute

    result = eval(Task(solver=agent_solver()))[0]

    assert result.status == "success"
    assert result.stats.model_usage["mockllm/model"].total_tokens == 5


def test_can_use_deprecated_sample_limit_exceeded_error() -> None:
    # SampleLimitExceededError is deprecated in favour of LimitExceededError.
    from inspect_ai.solver import SampleLimitExceededError  # type: ignore

    try:
        with token_limit(1):
            _record_token_usage(2)
            check_token_limit()
        pytest.fail("Expected SampleLimitExceededError")
    except SampleLimitExceededError as exc_info:  # type: ignore
        assert exc_info.__class__ == LimitExceededError
        assert exc_info.type == "token"


def _get_token_count() -> int:
    leaf = _limit.leaf_node.get()
    assert leaf is not None
    return sum(usage.total_tokens for usage in leaf._usage.values())


def _record_token_usage(total_tokens: int) -> None:
    record_model_usage("model", ModelUsage(total_tokens=total_tokens))
