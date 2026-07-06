import asyncio
import contextlib
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


class Wake:
    """One-shot wake signal that can be re-armed (set on completion / injection).

    Safe under cooperative scheduling: the only await is on ``wait()``; the
    re-arm assignment afterwards runs without a yield point, so a concurrent
    ``set()`` can't be lost between waking and re-arming.
    """

    def __init__(self) -> None:
        self._event = anyio.Event()

    def set(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()
        self._event = anyio.Event()


class aexit_shielded_when(contextlib.AbstractAsyncContextManager[Any]):
    """Wrap an async context manager so its `__aexit__` runs shielded when `shield()` is True.

    Lets a caller keep `async with X:` syntax while making the inner CM's
    teardown uninterruptible under a still-cancelled enclosing scope. `shield`
    is a callable so it can read state that is only set inside the `async with`
    body (e.g. a `cancelled_error` local that's `None` at construction time
    and assigned later).
    """

    def __init__(
        self,
        inner: contextlib.AbstractAsyncContextManager[Any],
        shield: Callable[[], bool],
    ) -> None:
        self._inner = inner
        self._shield = shield

    async def __aenter__(self) -> Any:
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        with anyio.CancelScope(shield=self._shield()):
            return await self._inner.__aexit__(exc_type, exc_value, traceback)


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
    from inspect_ai._util.asyncfiles import AsyncFilesystem
    from inspect_ai._util.platform import running_in_notebook

    async def _run_with_async_filesystem() -> T:
        async with AsyncFilesystem():
            return await coroutine

    if running_in_notebook():
        if current_async_backend() == "trio":
            raise RuntimeError(
                "run_coroutine cannot be used from within a running trio task"
            )
        init_nest_asyncio()
        return asyncio.run(_run_with_async_filesystem())

    backend = current_async_backend()
    if backend == "trio":
        # trio has no nest_asyncio equivalent so we cannot re-enter the
        # running loop from sync code (callers should use the _async variant)
        raise RuntimeError(
            "run_coroutine cannot be used from within a running trio task"
        )
    if backend is None:
        try:
            # sniffio can report no backend from synchronous callbacks even
            # though an asyncio loop is active.
            asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop, so start one on the configured backend.
            return anyio.run(
                _run_with_async_filesystem, backend=configured_async_backend()
            )
    # Running asyncio loop -- re-enter it via nest_asyncio.
    init_nest_asyncio()
    return asyncio.run(_run_with_async_filesystem())


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
