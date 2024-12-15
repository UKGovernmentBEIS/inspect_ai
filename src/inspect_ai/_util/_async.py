import asyncio
from typing import Any, Coroutine, TypeVar

import nest_asyncio  # type: ignore


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


def run_coroutine(coroutine: Coroutine[None, None, T]) -> T:
    try:
        # this will throw if there is no running loop
        asyncio.get_running_loop()

        # initialiase nest_asyncio then we are clear to run
        init_nest_asyncio()
        return asyncio.run(coroutine)

    except RuntimeError:
        # No running event loop so we are clear to run
        return asyncio.run(coroutine)
