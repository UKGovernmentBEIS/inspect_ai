import asyncio
from contextvars import ContextVar
from typing import Awaitable, Callable

from anyio.abc import TaskGroup
from typing_extensions import Unpack

from ._async import PosArgsT, current_async_backend


def run_in_background(
    func: Callable[[Unpack[PosArgsT]], Awaitable[None]],
    *args: Unpack[PosArgsT],
) -> None:
    """
    Runs the given asynchronous function in the background using the most appropriate form of structured concurrency.

    Args:
      func (Callable[[Unpack[PosArgsT]], Awaitable[None]]): The asynchronous function to run in the background.
      *args (Unpack[PosArgsT]): Positional arguments to pass to the function.

    Note:
      The passed function must ensure that it does not raise any exceptions. Exceptions
      that do escape are considered coding errors, and the behavior is not strictly
      defined. For example, if within the context of an eval, the eval will fail.
    """
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
                f"run_coroutine cannot be used {'with trio' if backend == 'trio' else 'outside of an async context'}"
            )


_background_task_group: ContextVar[TaskGroup | None] = ContextVar(
    "background_task_group", default=None
)


def set_background_task_group(tg: TaskGroup | None) -> None:
    _background_task_group.set(tg)


def background_task_group() -> TaskGroup | None:
    return _background_task_group.get()
