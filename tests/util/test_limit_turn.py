from typing import Generator

import anyio
import pytest

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util._async import tg_collect
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._solver import Generate, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._limit import (
    LimitExceededError,
    check_turn_limit,
    record_turn,
    suspend_turn_limit,
    turn_count,
    turn_limit,
)


@pytest.fixture
def model() -> Model:
    """A model which produces one assistant message (one turn) per generate call."""

    def repeat_forever(output: ModelOutput) -> Generator[ModelOutput, None, None]:
        while True:
            yield output

    output = ModelOutput.from_content("mockllm/model", "hello")
    return get_model("mockllm/model", custom_outputs=repeat_forever(output))


def test_can_record_turn_with_no_active_limits() -> None:
    record_turn()


def test_can_check_turn_limit_with_no_active_limits() -> None:
    check_turn_limit()


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        turn_limit(-1)


def test_can_create_with_none_limit() -> None:
    with turn_limit(None):
        _consume_turns(10)


def test_can_create_with_zero_limit() -> None:
    with turn_limit(0):
        pass


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    _consume_turns(10)

    with turn_limit(10):
        _consume_turns(10)


def test_raises_error_after_exactly_n_generations() -> None:
    with turn_limit(10) as limit:
        # The first 10 turns are allowed; the 11th exceeds the limit.
        _consume_turns(10)
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_turns(1)

    assert exc_info.value.type == "turn"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10
    assert exc_info.value.source is limit


def test_raises_error_when_limit_repeatedly_exceeded() -> None:
    with turn_limit(10):
        _consume_turns(10)
        with pytest.raises(LimitExceededError):
            _consume_turns(1)
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_turns(1)

    assert exc_info.value.type == "turn"
    assert exc_info.value.value == 12
    assert exc_info.value.limit == 10


def test_stack_can_trigger_outer_limit() -> None:
    _consume_turns(5)

    with turn_limit(10):
        _consume_turns(6)

        with turn_limit(11):
            with pytest.raises(LimitExceededError) as exc_info:
                # Should trigger outer limit (10).
                _consume_turns(5)

    assert exc_info.value.limit == 10


def test_stack_can_trigger_inner_limit() -> None:
    _consume_turns(5)

    with turn_limit(10):
        _consume_turns(1)

        with turn_limit(5):
            with pytest.raises(LimitExceededError) as exc_info:
                # Should trigger inner limit (5).
                _consume_turns(6)

    assert exc_info.value.limit == 5


def test_out_of_scope_limits_are_not_checked() -> None:
    with turn_limit(10):
        _consume_turns(5)

    _consume_turns(100)


def test_outer_limit_is_checked_after_inner_limit_popped() -> None:
    _consume_turns(5)

    with turn_limit(10):
        _consume_turns(5)

        with turn_limit(5):
            _consume_turns(1)

        with pytest.raises(LimitExceededError) as exc_info:
            # Should trigger outer limit (10).
            _consume_turns(5)

    assert exc_info.value.limit == 10
    assert exc_info.value.value == 11


def test_outermost_limit_raises_error_when_multiple_limits_exceeded() -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with turn_limit(1) as outer:
            with turn_limit(2):
                _consume_turns(10)

    # The outermost limit is the one that the error is raised against, despite both
    # limits being exceeded. This prevents sub-agent architectures from getting stuck
    # in an infinite loop.
    assert exc_info.value.limit == 1
    assert exc_info.value.source is outer


def test_can_get_limit_value() -> None:
    limit = turn_limit(10)

    assert limit.limit == 10


def test_can_update_limit_value() -> None:
    limit = turn_limit(10)

    with limit:
        _consume_turns(5)

        limit.limit = 20
        _consume_turns(15)

        limit.limit = 10

        with pytest.raises(LimitExceededError) as exc_info:
            check_turn_limit()
            assert exc_info.value.value == 20

        limit.limit = None
        _consume_turns(5)

    assert limit.limit is None


def test_can_get_usage_while_context_manager_open() -> None:
    with turn_limit(10) as limit:
        _consume_turns(5)

        assert limit.usage == 5


def test_can_get_usage_before_context_manager_opened() -> None:
    limit = turn_limit(10)

    assert limit.usage == 0


def test_can_get_usage_after_context_manager_closed() -> None:
    with turn_limit(10) as limit:
        _consume_turns(5)

    assert limit.usage == 5


def test_turn_count_none_when_no_active_limit() -> None:
    assert turn_count() is None


def test_turn_count_reports_turns() -> None:
    with turn_limit(10):
        _consume_turns(3)
        assert turn_count() == 3


def test_turn_count_reports_root_when_nested() -> None:
    # turn count reflects the outermost (sample-level) limit, not the inner scope
    with turn_limit(10):
        _consume_turns(2)
        with turn_limit(10):
            _consume_turns(1)
            assert turn_count() == 3


def test_can_get_usage_nested() -> None:
    with turn_limit(10) as limit_outer:
        _consume_turns(5)
        with turn_limit(10) as limit_inner:
            _consume_turns(5)

    assert limit_outer.usage == 10
    assert limit_inner.usage == 5


def test_can_get_usage_after_limit_error() -> None:
    with pytest.raises(LimitExceededError):
        with turn_limit(10) as limit:
            # Each turn is recorded and checked individually, so recording stops
            # at the turn which first exceeds the limit (the 11th).
            _consume_turns(15)

    assert limit.usage == 11


async def test_can_get_remaining() -> None:
    limit = turn_limit(10)
    with limit:
        _consume_turns(4)

        assert limit.remaining is not None
        assert limit.remaining == 6


def test_cannot_reuse_context_manager() -> None:
    limit = turn_limit(10)
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
    limit = turn_limit(10)

    with pytest.raises(RuntimeError) as exc_info:
        with limit:
            # Reusing the same Limit instance in a stack.
            with limit:
                pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


async def test_same_context_manager_across_async_contexts() -> None:
    async def async_task() -> None:
        _consume_turns(5)

        with turn_limit(10):
            # Incrementally use 10 turns (should not exceed the limit).
            for _ in range(10):
                _consume_turns(1)
                # Yield to the event loop to allow other coroutines to run.
                await anyio.sleep(0)
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_turns(1)
                assert exc_info.value.value == 11

    # This will result in 3 distinct "trees" each with 1 root node.
    await tg_collect([async_task for _ in range(3)])


def test_counts_one_turn_per_generation_end_to_end(model: Model) -> None:
    """The model generation path records exactly one turn per generate call."""

    @solver
    def generating_solver():
        async def solve(state: TaskState, generate: Generate):
            # Three generations against a turn_limit of 5 should not raise.
            with turn_limit(5) as limit:
                await model.generate("")
                await model.generate("")
                await model.generate("")
                assert limit.usage == 3
            return state

        return solve

    result = eval(Task(solver=generating_solver()))[0]

    assert result.status == "success"


def test_generation_raises_when_turn_limit_exceeded(model: Model) -> None:
    """A turn_limit applied around generations raises after N+1 generations."""

    @solver
    def generating_solver():
        async def solve(state: TaskState, generate: Generate):
            with turn_limit(2):
                await model.generate("")
                await model.generate("")
                with pytest.raises(LimitExceededError) as exc_info:
                    # The third generation exceeds the limit of 2.
                    await model.generate("")
                assert exc_info.value.type == "turn"
                assert exc_info.value.value == 3
                assert exc_info.value.limit == 2
            return state

        return solve

    result = eval(Task(solver=generating_solver()))[0]

    assert result.status == "success"


def test_suspend_turn_limit_skips_recording_and_check() -> None:
    with turn_limit(10) as limit:
        with suspend_turn_limit():
            _consume_turns(100)
        assert limit.usage == 0


def test_suspend_turn_limit_resumes_metering_on_exit() -> None:
    with turn_limit(10) as limit:
        with suspend_turn_limit():
            _consume_turns(100)

        assert limit.usage == 0

        _consume_turns(10)
        with pytest.raises(LimitExceededError):
            _consume_turns(1)


def test_suspend_turn_limit_with_no_active_limit() -> None:
    with suspend_turn_limit():
        _consume_turns(100)


def test_suspend_turn_limit_nested() -> None:
    with turn_limit(10) as limit:
        with suspend_turn_limit():
            _consume_turns(50)
            with suspend_turn_limit():
                _consume_turns(50)
            _consume_turns(50)
        assert limit.usage == 0


def test_suspend_turn_limit_hides_inner_turn_limit() -> None:
    with turn_limit(10) as outer:
        with suspend_turn_limit():
            with turn_limit(5) as inner:
                _consume_turns(100)
            assert inner.usage == 0
        assert outer.usage == 0


def _consume_turns(turns: int) -> None:
    # record_turn() both records the turn and checks the active limit.
    for _ in range(turns):
        record_turn()
