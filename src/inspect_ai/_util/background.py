import asyncio
from contextvars import ContextVar
from typing import Any, Callable, Coroutine

from anyio.abc import TaskGroup
from typing_extensions import Unpack

from ._async import PosArgsT, current_async_backend
from .task import no_active_task


def run_in_background(
    func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, None]],
    *args: Unpack[PosArgsT],
) -> None:
    """
    Runs the given asynchronous function in the background using the most appropriate form of structured concurrency.

    Args:
      func (Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, None]]): The asynchronous function to run in the background.
      *args (Unpack[PosArgsT]): Positional arguments to pass to the function.

    The function runs with no active task (``task_active()`` is ``None``),
    since run-level background work can outlive the task that started it and
    serve other tasks. Other context (such as the active sample) is inherited
    as before.

    Note:
      The passed function must ensure that it does not raise any exceptions. Exceptions
      that do escape are considered coding errors, and the behavior is not strictly
      defined. For example, if within the context of an eval, the eval will fail.
    """
    # the spawned work copies the context current at start_soon/create_task
    with no_active_task():
        _start_in_background(func, *args)


def _start_in_background(
    func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, None]],
    *args: Unpack[PosArgsT],
) -> None:
    if tg := background_task_group():
        tg.start_soon(func, *args)
    else:
        if (backend := current_async_backend()) == "asyncio":

            async def wrapper() -> None:
                try:
                    await func(*args)
                except Exception as ex:
                    raise RuntimeError("Exception escaped from background task") from ex

            asyncio.create_task(wrapper())
        else:
            raise RuntimeError(
                f"run_in_background cannot be used {'with trio' if backend == 'trio' else 'outside of an async context'}"
            )


_background_task_group: ContextVar[TaskGroup | None] = ContextVar(
    "background_task_group", default=None
)


def set_background_task_group(tg: TaskGroup | None) -> None:
    _background_task_group.set(tg)


def background_task_group() -> TaskGroup | None:
    return _background_task_group.get()
