import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_coroutine(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine synchronosly. Like asyncio.run but handles nested async contexts."""
    # if we are already in an event loop, patch it so we can call asyncio.run
    try:
        loop = get_running_loop()
        if loop and not hasattr(loop, "_nest_patched"):
            import nest_asyncio  # type: ignore

            nest_asyncio.apply()
    except RuntimeError:
        pass

    return asyncio.run(coro)


def is_callable_coroutine(func_or_cls: Any) -> bool:
    if asyncio.iscoroutinefunction(func_or_cls):
        return True
    elif callable(func_or_cls):
        return asyncio.iscoroutinefunction(func_or_cls.__call__)
    return False


def get_running_loop() -> asyncio.AbstractEventLoop | None:
    """Get the running event loop if one exists, otherwise return None."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
