import asyncio
import contextlib
import inspect
import os
import signal
import threading
from types import FrameType, TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Iterable,
    Literal,
    NoReturn,
    TypeVar,
    TypeVarTuple,
    Unpack,
    cast,
)

import anyio
import nest_asyncio2 as nest_asyncio  # type: ignore
import sniffio

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
    with unwrap_exception_group(None if exception_group else "first"):
        results: list[tuple[int, T]] = []

        async with anyio.create_task_group() as tg:

            async def run_task(func: Callable[[], Awaitable[T]], index: int) -> None:
                result = await func()
                results.append((index, result))

            for index, func in enumerate(funcs):
                tg.start_soon(run_task, func, index)

        # sort results by original index and return just the values
        return [r for _, r in sorted(results)]


class unwrap_exception_group:
    """Unwrap an `ExceptionGroup` that leaves the block, raising its exception bare.

    See `raise_unwrapped()` for the chain the exception keeps: its own, or
    the group as its suppressed context when the group carried more.

    Use `with`, or `async with` in the same statement as the task group:
    `async with unwrap_exception_group(), anyio.create_task_group() as tg:`.
    It is a class rather than a generator, and its async exit raises before
    any coroutine runs: an exception raised out of a generator or coroutine
    frame changes type (`StopIteration` becomes `RuntimeError`).

    Exception classes that override `__class__`, `__cause__` or `__setattr__`
    are not supported.

    Args:
       unwrap: "single" raises the exception when the group holds exactly
          one and the group otherwise; "first" raises the first exception
          and drops the rest; `None` leaves the group as it is.
    """

    def __init__(self, unwrap: Literal["single", "first"] | None = "single") -> None:
        self._unwrap = unwrap

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # match the exception's own type, not a __class__ attribute it defines
        if (
            self._unwrap is None
            or exc_type is None
            or not issubclass(exc_type, ExceptionGroup)
        ):
            return
        group = cast(ExceptionGroup[Exception], exc_value)
        if self._unwrap == "single" and len(group.exceptions) != 1:
            return
        raise_unwrapped(group, group.exceptions[0])

    async def __aenter__(self) -> None:
        return None

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[None]:
        self.__exit__(exc_type, exc_value, traceback)
        return _completed()


async def _completed() -> None:
    return None


def raise_unwrapped(group: BaseException, error: BaseException) -> NoReturn:
    """Raise `error`, taken from `group`, keeping what `group` carried reachable.

    `error` keeps its own `__cause__`. When `group` carries nothing `error`
    does not, `error` also keeps its own `__context__` and
    `__suppress_context__`, so its traceback reads as it would without the
    group. Otherwise its context is `group`, suppressed as with
    `raise ... from`, so what `group` carried stays in its history, where
    `find_control_flow()` looks. If `group` reaches `error`'s own context
    only through that context, which this replaces, the new context is a
    group of `error`'s own context and `group`, so neither is lost.

    `group` carries something `error` does not when it holds other errors
    (through nested groups), or when a group around `error` has a context or
    cause leading to an `Exception` that is not already in `error`'s own
    history. Groups, and exceptions that are not `Exception` subclasses
    (cancellation, `KeyboardInterrupt`, `SystemExit`, ...), count only for
    what they lead to: `find_control_flow()` looks only for `Exception`
    subclasses. So a task group whose host was cancelled, or that was raised
    while handling another group of the same error, carries nothing extra.

    It may be called inside or after the handler for `group`. Exception
    classes that override `__class__`, `__cause__` or `__setattr__` are not
    supported.

    Args:
       group: The exception caught: `error`, or a group holding it.
       error: The exception from `group` to raise.
    """
    # the stored attributes, past any attributes of the subclass's own
    context = vars(BaseException)["__context__"]
    suppress_context = vars(BaseException)["__suppress_context__"]
    own_context = context.__get__(error)
    if _carries_only(group, error):
        saved_context = own_context
        saved_suppress_context = suppress_context.__get__(error)
    elif own_context is None or id(own_context) in _history([group], leaf=error):
        saved_context, saved_suppress_context = group, True
    else:
        saved_context = BaseExceptionGroup(
            "unwrapped exception history", [own_context, group]
        )
        saved_suppress_context = True
    # raising sets the context to the exception being handled, if any
    try:
        raise error
    finally:
        context.__set__(error, saved_context)
        suppress_context.__set__(error, saved_suppress_context)


def _carries_only(group: BaseException, error: BaseException) -> bool:
    wrappers: list[BaseException] = []
    node = group
    while node is not error:
        # match the exception's own type, not a __class__ attribute it defines
        if not issubclass(type(node), BaseExceptionGroup):
            return False
        members = cast(BaseExceptionGroup[BaseException], node).exceptions
        if len(members) != 1:
            return False
        wrappers.append(node)
        node = members[0]
    own = _history([error])
    carried = _history([linked for wrapper in wrappers for linked in _links(wrapper)])
    return all(
        id(e) in own
        or not issubclass(type(e), Exception)
        or issubclass(type(e), BaseExceptionGroup)
        for e in carried.values()
    )


def _history(
    roots: list[BaseException], leaf: BaseException | None = None
) -> dict[int, BaseException]:
    """The exceptions reachable from `roots` by cause, context and group members.

    The cause and context of `leaf` are not followed.
    """
    seen: dict[int, BaseException] = {}
    stack = list(roots)
    while stack:
        e = stack.pop()
        if id(e) in seen:
            continue
        seen[id(e)] = e
        if e is not leaf:
            stack.extend(_links(e))
        if issubclass(type(e), BaseExceptionGroup):
            stack.extend(cast(BaseExceptionGroup[BaseException], e).exceptions)
    return seen


def _links(e: BaseException) -> list[BaseException]:
    cause = vars(BaseException)["__cause__"].__get__(e)
    context = vars(BaseException)["__context__"].__get__(e)
    return [linked for linked in (cause, context) if linked is not None]


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
            pass
        else:
            backend = "asyncio"
    if backend is None:
        # Leave the loop-probe handler so its error cannot become task context.
        return _anyio_run_released(_run_with_async_filesystem)
    # Running asyncio loop -- re-enter it via nest_asyncio.
    init_nest_asyncio()
    return asyncio.run(_run_with_async_filesystem())


def _anyio_run_released(func: Callable[[], Awaitable[T]]) -> T:
    """Run `func` on a fresh event loop, then release anyio's per-loop state.

    Without the release step, every call leaks its entire return value.
    Here's why: anyio keeps per-event-loop state in a global
    WeakKeyDictionary, `anyio.lowlevel._run_vars`, where the key is the loop
    itself. Weak keys normally guarantee cleanup — once nothing else
    references the loop, its entry disappears. But when `func` uses anyio's
    threadpool, anyio stores the run's root task in that entry, and a task
    always references the loop it ran on. So the entry's value points back at
    its own key: the dictionary keeps the task alive, the task keeps the loop
    alive, and the "weak" entry becomes immortal — along with the task's
    result, which is our coroutine's return value. Popping the dead loop's
    entry after the run breaks the cycle so everything can be collected.
    """
    from anyio.lowlevel import _run_vars

    loop: asyncio.AbstractEventLoop | None = None

    async def capture_loop_and_run() -> T:
        nonlocal loop
        if current_async_backend() == "asyncio":
            loop = asyncio.get_running_loop()
        return await func()

    try:
        return anyio.run(capture_loop_and_run, backend=configured_async_backend())
    finally:
        if loop is not None:
            _run_vars.pop(loop, None)


def run_main(main: Callable[[], Coroutine[None, None, T]]) -> T:
    """Run `main` on a new event loop of the configured backend.

    On trio, the first SIGINT cancels `main`, which can still clean up (an
    eval writes its cancelled logs), and `KeyboardInterrupt` is raised once
    it finishes. Without this, trio raises `KeyboardInterrupt` into whatever
    code is running when the signal lands. Later SIGINTs go to trio's own
    handler, which does not stop shielded cleanup that is waiting. On
    asyncio, `asyncio.run()` handles SIGINT.
    """
    backend = configured_async_backend()
    if (
        backend == "trio"
        and threading.current_thread() is threading.main_thread()
        and signal.getsignal(signal.SIGINT) is signal.default_int_handler
    ):
        return anyio.run(_trio_cancel_on_sigint, main, backend="trio")
    return anyio.run(main, backend=backend)


async def _trio_cancel_on_sigint(main: Callable[[], Coroutine[None, None, T]]) -> T:
    import trio

    trio_handler = signal.getsignal(signal.SIGINT)
    token = trio.lowlevel.current_trio_token()
    scope = trio.CancelScope()
    interrupted = False

    def cancel_main(signum: int, frame: FrameType | None) -> None:
        nonlocal interrupted
        interrupted = True
        # trio's handler raises KeyboardInterrupt on the next SIGINT
        signal.signal(signal.SIGINT, trio_handler)
        token.run_sync_soon(scope.cancel)

    signal.signal(signal.SIGINT, cancel_main)
    try:
        with scope:
            result = await main()
    except BaseExceptionGroup as ex:
        # a second SIGINT that lands in a child task arrives grouped
        if interrupted and ex.split((KeyboardInterrupt, trio.Cancelled))[1] is None:
            raise KeyboardInterrupt from None
        raise
    finally:
        # leave a handler that `main` installed in place
        if signal.getsignal(signal.SIGINT) is cancel_main:
            signal.signal(signal.SIGINT, trio_handler)
    if interrupted:
        raise KeyboardInterrupt
    return result


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
