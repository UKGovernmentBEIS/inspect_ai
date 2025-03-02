import asyncio
from typing import Any, TypeVar

import nest_asyncio  # type: ignore
import sniffio


def is_callable_coroutine(func_or_cls: Any) -> bool:
    if asyncio.iscoroutinefunction(func_or_cls):
        return True
    elif callable(func_or_cls):
        return asyncio.iscoroutinefunction(func_or_cls.__call__)
    return False


T = TypeVar("T")


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
