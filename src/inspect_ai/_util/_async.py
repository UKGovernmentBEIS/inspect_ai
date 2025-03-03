import inspect
from typing import Any, Awaitable, TypeVar

import nest_asyncio  # type: ignore
import sniffio


def is_callable_coroutine(func_or_cls: Any) -> bool:
    if inspect.iscoroutinefunction(func_or_cls):
        return True
    elif callable(func_or_cls):
        return inspect.iscoroutinefunction(func_or_cls.__call__)
    return False


T = TypeVar("T")


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
