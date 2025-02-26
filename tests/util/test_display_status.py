import asyncio
from typing import get_args

import pytest

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import status_counter
from inspect_ai.util._display import DisplayType


@pytest.mark.parametrize("display_type", get_args(DisplayType))
def test_can_display_status(display_type: DisplayType):
    # This test doesn't actually verify the UI; it just exercises the code path.
    result = eval(status_task(), model="mockllm/mockllm", display=display_type)

    assert result[0].status == "success"


@task
def status_task():
    return Task(
        dataset=[Sample(input="Just reply with Hello World")], solver=[status_solver()]
    )


@solver
def status_solver():
    async def solve(state: TaskState, generate: Generate):
        status_counter("My status", "1")
        status_counter("My status", "2")
        # The footer is throttled at 1 Hz, so sleep for longer than that.
        await asyncio.sleep(1.1)
        status_counter("My status", "3")
        return state

    return solve
