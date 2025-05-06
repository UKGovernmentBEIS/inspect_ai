import sys
from typing import Awaitable, TypeVar, cast

import anyio

from ._span import span

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


T = TypeVar("T")


async def collect(*tasks: Awaitable[T]) -> list[T]:
    """Run and collect the results of one or more async coroutines.

    Similar to [`asyncio.gather()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather),
    but also works when [Trio](https://trio.readthedocs.io/en/stable/) is the async backend.

    Automatically includes each task in a `span()`, which
    ensures that its events are grouped together in the transcript.

    Using `collect()` in preference to `asyncio.gather()` is highly recommended
    for both Trio compatibility and more legible transcript output.

    Args:
        *tasks: Tasks to run

    Returns:
        List of task results.
    """
    results: list[None | T] = [None] * len(tasks)

    try:
        async with anyio.create_task_group() as tg:

            async def run_task(index: int, task: Awaitable[T]) -> None:
                async with span(f"task-{index + 1}", type="task"):
                    results[index] = await task

            for i, task in enumerate(tasks):
                tg.start_soon(run_task, i, task)
    except ExceptionGroup as ex:
        if len(ex.exceptions) == 1:
            raise ex.exceptions[0] from None
        else:
            raise

    return cast(list[T], results)
