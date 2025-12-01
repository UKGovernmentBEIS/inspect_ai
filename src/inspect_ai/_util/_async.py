import asyncio
import inspect
import os
import sys
from logging import Logger
from typing import Any, Awaitable, Callable, Coroutine, Iterable, Literal, TypeVar, cast

import anyio
import nest_asyncio2 as nest_asyncio  # type: ignore
import sniffio

if sys.version_info >= (3, 11):
    from typing import TypeVarTuple, Unpack
else:
    from exceptiongroup import ExceptionGroup
    from typing_extensions import TypeVarTuple, Unpack


PosArgsT = TypeVarTuple("PosArgsT")


def is_callable_coroutine(func_or_cls: Any) -> bool:
    if inspect.iscoroutinefunction(func_or_cls):
        return True
    elif inspect.isasyncgenfunction(func_or_cls):
        return True
    elif callable(func_or_cls):
        return inspect.iscoroutinefunction(
            func_or_cls.__call__
        ) or inspect.isasyncgenfunction(func_or_cls.__call__)
    return False


T = TypeVar("T")


async def tg_collect(
    funcs: Iterable[Callable[[], Awaitable[T]]], exception_group: bool = False
) -> list[T]:
    """Runs all of the passed async functions and collects their results.

    The results will be returned in the same order as the input `funcs`.

    Args:
       funcs: Iterable of async functions.
       exception_group: `True` to raise an ExceptionGroup or
          `False` (the default) to raise only the first exception.

    Returns:
       List of results of type T.

    Raises:
       Exception: First exception occurring in failed tasks
          (for `exception_group == False`, the default)
       ExceptionGroup: Exceptions that occurred in failed tasks
         (for `exception_group == True`)
    """
    try:
        results: list[tuple[int, T]] = []

        async with anyio.create_task_group() as tg:

            async def run_task(func: Callable[[], Awaitable[T]], index: int) -> None:
                result = await func()
                results.append((index, result))

            for index, func in enumerate(funcs):
                tg.start_soon(run_task, func, index)

        # sort results by original index and return just the values
        return [r for _, r in sorted(results)]
    except ExceptionGroup as ex:
        if exception_group:
            raise
        else:
            raise ex.exceptions[0] from None


async def coro_print_exceptions(
    context: str,
    func: Callable[[Unpack[PosArgsT]], Awaitable[Any]],
    *args: Unpack[PosArgsT],
) -> None:
    try:
        await func(*args)
    except Exception as ex:
        print(f"Error {context}: {ex}")


async def coro_log_exceptions(
    logger: Logger,
    context: str,
    func: Callable[[Unpack[PosArgsT]], Awaitable[Any]],
    *args: Unpack[PosArgsT],
) -> None:
    try:
        await func(*args)
    except Exception as ex:
        logger.warning(f"Error {context}: {ex}")


_initialised_nest_asyncio: bool = False


def init_nest_asyncio() -> None:
    global _initialised_nest_asyncio
    if not _initialised_nest_asyncio:
        nest_asyncio.apply()
        _initialised_nest_asyncio = True


def run_coroutine(coroutine: Coroutine[None, None, T]) -> T:
    from inspect_ai._util.platform import running_in_notebook

    if current_async_backend() == "trio":
        raise RuntimeError("run_coroutine cannot be used with trio")

    if running_in_notebook():
        init_nest_asyncio()
        return asyncio.run(coroutine)
    else:
        try:
            # this will throw if there is no running loop
            asyncio.get_running_loop()

            # initialize nest_asyncio then we are clear to run
            init_nest_asyncio()

        except RuntimeError:
            # No running event loop so we are clear to run. Exit the exception handler
            # and run it.
            pass

        return asyncio.run(coroutine)


def current_async_backend() -> Literal["asyncio", "trio"] | None:
    try:
        return _validate_backend(sniffio.current_async_library().lower())
    except sniffio.AsyncLibraryNotFoundError:
        return None


def configured_async_backend() -> Literal["asyncio", "trio"]:
    backend = os.environ.get("INSPECT_ASYNC_BACKEND", "asyncio").lower() or "asyncio"
    return _validate_backend(backend)


def _validate_backend(backend: str) -> Literal["asyncio", "trio"]:
    if backend in ["asyncio", "trio"]:
        return cast(Literal["asyncio", "trio"], backend)
    else:
        raise RuntimeError(f"Unknown async backend: {backend}")
