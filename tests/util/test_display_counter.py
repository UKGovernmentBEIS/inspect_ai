from typing import get_args

import anyio
import pytest

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import display_counter
from inspect_ai.util._display import DisplayType


@pytest.mark.parametrize("display_type", get_args(DisplayType))
def test_can_display_counter(display_type: DisplayType):
    # This test doesn't actually verify the UI; it just exercises the code path.
    result = eval(counter_task(), model="mockllm/mockllm", display=display_type)

    assert result[0].status == "success"


@task
def counter_task():
    return Task(
        dataset=[Sample(input="Just reply with Hello World")], solver=[counter_solver()]
    )


@solver
def counter_solver():
    async def solve(state: TaskState, generate: Generate):
        display_counter("My counter", "1")
        display_counter("My counter", "2")
        # The footer is throttled at 1 Hz, so sleep for longer than that.
        await anyio.sleep(1.1)
        display_counter("My counter", "3")
        return state

    return solve
