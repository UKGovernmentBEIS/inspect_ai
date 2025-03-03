import inspect
from typing import Any, Awaitable, TypeVar

import anyio
import nest_asyncio  # type: ignore
import sniffio


def is_callable_coroutine(func_or_cls: Any) -> bool:
    if inspect.iscoroutinefunction(func_or_cls):
        return True
    elif callable(func_or_cls):
        return inspect.iscoroutinefunction(func_or_cls.__call__)
    return False


T = TypeVar("T")


async def tg_collect_or_raise(coros: list[Awaitable[T]]) -> list[T]:
    """Runs all of the passed coroutines collecting their results.

    If an exception occurs in any of the tasks then the other tasks
    are cancelled and the exception is raised.

    Args:
       coros: List of coroutines

    Returns:
       List of results if no exceptions occurred.

    Raises:
       Exception: The first exception occurring in any of the coroutines.
    """
    results: list[tuple[int, T]] = []
    first_exception: Exception | None = None

    async with anyio.create_task_group() as tg:

        async def run_task(task: Awaitable[T], index: int) -> None:
            nonlocal first_exception
            try:
                result = await task
                results.append((index, result))
            except Exception as exc:
                if first_exception is None:
                    first_exception = exc
                tg.cancel_scope.cancel()

        for i, coro in enumerate(coros):
            tg.start_soon(run_task, coro, i)

    if first_exception:
        raise first_exception

    # sort results by original index and return just the values
    return [r for _, r in sorted(results)]


async def ignore_exceptions(coro: Awaitable[T]) -> None:
    try:
        await coro
    except Exception:
        pass


async def print_exceptions(coro: Awaitable[T], context: str) -> None:
    try:
        await coro
    except Exception as ex:
        print(f"Error {context}: {ex}")


_initialised_nest_asyncio: bool = False


def init_nest_asyncio() -> None:
    global _initialised_nest_asyncio
    if not _initialised_nest_asyncio:
        nest_asyncio.apply()
        _initialised_nest_asyncio = True


def get_current_async_library() -> str | None:
    try:
        return sniffio.current_async_library()
    except sniffio.AsyncLibraryNotFoundError:
        return None
