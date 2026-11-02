import dataclasses
import functools
import gc
import os
import subprocess
import sys
import textwrap
import threading
import weakref
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Literal,
    NoReturn,
)

import anyio.to_thread
import pytest

from inspect_ai._util._async import (
    raise_unwrapped,
    run_coroutine,
    tg_collect,
    unwrap_exception_group,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.util import collect
from inspect_ai.util._sandbox.service import find_control_flow


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
def test_run_coroutine_preserves_task_errors(backend: str) -> None:
    """The internal loop probe must not become context for task failures."""
    # Isolate the no-loop path from nest_asyncio and pytest's async state.
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            textwrap.dedent("""
                import anyio
                from inspect_ai._util._async import run_coroutine
                from inspect_ai.util._anyio import inner_exception

                cleaned_up = []

                async def fail():
                    try:
                        await anyio.sleep(0)
                        raise ValueError("intended worker failure")
                    finally:
                        cleaned_up.append(True)

                async def fail_group():
                    async with anyio.create_task_group() as tasks:
                        tasks.start_soon(fail)

                async def capture():
                    try:
                        await fail_group()
                    except Exception as group:
                        return group
                    raise AssertionError("worker did not fail")

                def check_error(group):
                    assert group.__context__ is None, repr(group.__context__)
                    error = inner_exception(group)
                    assert isinstance(error, ValueError), repr(error)
                    assert str(error) == "intended worker failure"

                check_error(run_coroutine(capture()))
                try:
                    run_coroutine(fail_group())
                except Exception as group:
                    check_error(group)
                else:
                    raise AssertionError("worker did not fail")
                assert cleaned_up == [True, True]
            """),
        ],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": backend},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_run_main_trio_sigint() -> None:
    """Under trio, Ctrl-C cancels run_main()'s coroutine, then raises KeyboardInterrupt."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            textwrap.dedent("""
                import signal
                import time

                import anyio
                from inspect_ai._util._async import run_main

                cleaned_up = []
                reached = []

                async def returns():
                    return "result"

                async def fails():
                    raise ValueError("main failed")

                async def cancelled():
                    signal.raise_signal(signal.SIGINT)
                    await anyio.sleep(30)

                async def cleans_up():
                    signal.raise_signal(signal.SIGINT)
                    try:
                        await anyio.sleep(30)
                    except anyio.get_cancelled_exc_class():
                        cleaned_up.append(True)
                        return "cleaned up"

                async def interrupted_twice_without_yielding():
                    signal.raise_signal(signal.SIGINT)
                    reached.append("first")
                    signal.raise_signal(signal.SIGINT)
                    reached.append("second")

                async def interrupted_twice_in_child():
                    async def child():
                        signal.raise_signal(signal.SIGINT)
                        try:
                            await anyio.sleep(30)
                        finally:
                            with anyio.CancelScope(shield=True):
                                signal.raise_signal(signal.SIGINT)
                                await anyio.sleep(30)

                    async with anyio.create_task_group() as tg:
                        tg.start_soon(child)

                def check_interrupted(main):
                    start = time.monotonic()
                    try:
                        run_main(main)
                    except KeyboardInterrupt as ex:
                        assert type(ex) is KeyboardInterrupt, repr(ex)
                    else:
                        raise AssertionError(f"{main.__name__}: no KeyboardInterrupt")
                    assert time.monotonic() - start < 10, main.__name__
                    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

                assert run_main(returns) == "result"
                try:
                    run_main(fails)
                except ValueError as ex:
                    assert str(ex) == "main failed"
                else:
                    raise AssertionError("fails: no ValueError")
                assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

                check_interrupted(cancelled)
                check_interrupted(cleans_up)
                assert cleaned_up == [True]
                check_interrupted(interrupted_twice_without_yielding)
                assert reached == ["first"], reached
                check_interrupted(interrupted_twice_in_child)

                def own_handler(signum, frame):
                    pass

                async def installs_handler():
                    signal.signal(signal.SIGINT, own_handler)
                    return "installed"

                assert run_main(installs_handler) == "installed"
                assert signal.getsignal(signal.SIGINT) is own_handler
            """),
        ],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": "trio"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_run_coroutine_releases_result() -> None:
    """run_coroutine() must not retain a reference to the coroutine's result.

    When the coroutine uses anyio's threadpool (as the local-file read path
    does), anyio caches the run's root task in a loop-keyed WeakKeyDictionary
    (anyio.lowlevel._run_vars); the task references the loop (the weak key),
    so the entry — and the task's result — is never evicted. Every such
    run_coroutine() call would otherwise pin its entire return value forever
    (e.g. each EvalSample yielded by read_eval_log_samples).
    """

    class Payload:
        pass

    async def make_payload(workers: list[threading.Thread]) -> Payload:
        workers.append(await anyio.to_thread.run_sync(threading.current_thread))
        return Payload()

    def released_result_ref() -> "weakref.ref[Payload]":
        workers: list[threading.Thread] = []
        result = run_coroutine(make_payload(workers))
        # The worker retains the root task and its result until it exits.
        # Keep thread references in this helper so they are released before GC.
        for worker in workers:
            worker.join(timeout=10)
            assert not worker.is_alive(), "AnyIO worker did not exit"
        return weakref.ref(result)

    ref = released_result_ref()
    gc.collect()
    assert ref() is None, "result still referenced after release"


async def _fail_with_cause() -> None:
    try:
        raise KeyError("context")
    except KeyError:
        raise RuntimeError("task failed") from ValueError("cause")


def _failing_tasks(count: int) -> list[Callable[[], Awaitable[None]]]:
    """Tasks that all fail, each only after every one has started."""
    started = 0
    all_started = anyio.Event()

    async def fail(index: int) -> None:
        nonlocal started
        # shielded, so a sibling's failure cannot cancel this one first
        with anyio.CancelScope(shield=True):
            started += 1
            if started == count:
                all_started.set()
            await all_started.wait()
            raise RuntimeError(f"task {index} failed")

    return [functools.partial(fail, index) for index in range(count)]


def _assert_cause_kept(error: BaseException) -> None:
    assert repr(error.__cause__) == "ValueError('cause')"
    assert repr(error.__context__) == "KeyError('context')"
    assert error.__suppress_context__


def _raise_wrapped() -> NoReturn:
    raise RuntimeError("wrapped")


async def _fail_implicitly() -> None:
    try:
        raise ValueError("context")
    except ValueError:
        _raise_wrapped()


async def _fail_explicitly() -> None:
    try:
        raise KeyError("context")
    except KeyError:
        raise RuntimeError("wrapped") from ValueError("cause")


async def _fail_from_none() -> None:
    try:
        raise KeyError("context")
    except KeyError:
        raise RuntimeError("wrapped") from None


@pytest.mark.parametrize(
    "fail,cause,context,suppressed",
    [
        (_fail_implicitly, "None", "ValueError('context')", False),
        (_fail_explicitly, "ValueError('cause')", "KeyError('context')", True),
        (_fail_from_none, "None", "KeyError('context')", True),
    ],
    ids=["implicit", "explicit", "from-none"],
)
@pytest.mark.parametrize("unwrap", ["single", "first"])
async def test_unwrapped_task_error_keeps_its_chain(
    fail: Callable[[], Coroutine[Any, Any, None]],
    cause: str,
    context: str,
    suppressed: bool,
    unwrap: Literal["single", "first"],
) -> None:
    with pytest.raises(RuntimeError, match="wrapped") as excinfo:
        async with unwrap_exception_group(unwrap), anyio.create_task_group() as tg:
            tg.start_soon(fail)
    error = excinfo.value
    assert repr(error.__cause__) == cause
    assert repr(error.__context__) == context
    assert error.__suppress_context__ is suppressed


async def test_first_error_keeps_dropped_sibling_termination() -> None:
    started = anyio.Event()
    termination = TerminateSampleError("stop")

    async def fail() -> None:
        await started.wait()
        raise RuntimeError("first")

    async def terminate_when_cancelled() -> None:
        try:
            started.set()
            await anyio.sleep_forever()
        finally:
            raise termination

    with pytest.raises(RuntimeError, match="first") as excinfo:
        await tg_collect([fail, terminate_when_cancelled])
    # the dropped sibling stays in the error's (suppressed) history
    assert isinstance(excinfo.value.__context__, ExceptionGroup)
    assert excinfo.value.__suppress_context__
    assert find_control_flow(excinfo.value) is termination


def _raise(error: BaseException) -> NoReturn:
    raise error


def _group_with_context(leaf: Exception, termination: Exception) -> ExceptionGroup:
    try:
        try:
            raise termination
        except TerminateSampleError:
            _raise(ExceptionGroup("cleanup", [leaf]))
    except ExceptionGroup as group:
        return group


def _group_with_cause(leaf: Exception, termination: Exception) -> ExceptionGroup:
    group = ExceptionGroup("cleanup", [leaf])
    group.__cause__ = termination
    return group


def _nested_group_with_context(
    leaf: Exception, termination: Exception
) -> ExceptionGroup:
    return ExceptionGroup("outer", [_group_with_context(leaf, termination)])


@pytest.mark.parametrize(
    "make_group",
    [_group_with_context, _group_with_cause, _nested_group_with_context],
    ids=["context", "cause", "nested"],
)
async def test_unwrapped_error_keeps_its_wrappers_termination(
    make_group: Callable[[Exception, Exception], ExceptionGroup],
) -> None:
    leaf = RuntimeError("leaf")
    termination = TerminateSampleError("stop now")
    group = make_group(leaf, termination)

    with pytest.raises(RuntimeError, match="leaf") as excinfo:
        try:
            _raise(group)
        except ExceptionGroup as ex:
            raise_unwrapped(ex, leaf)
    # the group carried the termination, so it stays as suppressed context
    assert excinfo.value.__context__ is group
    assert excinfo.value.__suppress_context__
    assert find_control_flow(excinfo.value) is termination


@pytest.mark.parametrize("selected", ["error", "group"])
@pytest.mark.parametrize("link", ["context", "cause"])
async def test_unwrapped_error_keeps_its_own_termination(
    selected: Literal["error", "group"], link: Literal["context", "cause"]
) -> None:
    termination = TerminateSampleError("stop now")
    leaf = RuntimeError("leaf")
    error: Exception = leaf if selected == "error" else ExceptionGroup("inner", [leaf])
    setattr(error, f"__{link}__", termination)
    outer = ExceptionGroup("outer", [error])
    outer_cause = ValueError("outer cause")
    outer.__cause__ = outer_cause

    with pytest.raises(type(error)) as excinfo:
        with unwrap_exception_group():
            raise outer
    assert excinfo.value is error
    assert error.__suppress_context__
    # the outer group carried its cause, so it stays as context, next to the
    # error's own context
    if link == "context":
        assert isinstance(error.__context__, BaseExceptionGroup)
        assert error.__context__.exceptions == (termination, outer)
    else:
        assert error.__cause__ is termination
        assert error.__context__ is outer
    assert outer.__cause__ is outer_cause
    assert find_control_flow(error) is termination


async def test_collect_keeps_task_error_cause() -> None:
    with pytest.raises(RuntimeError, match="task failed") as excinfo:
        await collect(_fail_with_cause())
    _assert_cause_kept(excinfo.value)


async def test_tg_collect_keeps_task_error_cause() -> None:
    with pytest.raises(RuntimeError, match="task failed") as excinfo:
        await tg_collect([_fail_with_cause])
    _assert_cause_kept(excinfo.value)


async def test_collect_and_tg_collect_unwrap_rules() -> None:
    # collect() raises the group when several tasks fail
    with pytest.raises(ExceptionGroup) as group:
        await collect(*[task() for task in _failing_tasks(2)])
    assert len(group.value.exceptions) == 2

    # tg_collect() raises one of them bare
    with pytest.raises(RuntimeError, match="failed"):
        await tg_collect(_failing_tasks(2))

    # unless it is asked for the group
    with pytest.raises(ExceptionGroup) as group:
        await tg_collect([_fail_with_cause], exception_group=True)
    assert len(group.value.exceptions) == 1


async def test_unwrapped_task_errors_keep_their_type() -> None:
    async def empty() -> AsyncIterator[None]:
        return
        yield

    async def exhausted() -> None:
        await anext(empty())

    with pytest.raises(StopAsyncIteration):
        await collect(exhausted())

    # the scheduler and the debug_errors task runner use "first"
    with pytest.raises(StopAsyncIteration):
        async with unwrap_exception_group("first"), anyio.create_task_group() as tg:
            tg.start_soon(exhausted)

    # raised in the body itself, the error crosses the helper's async exit
    cause = ValueError("cause")
    policies: list[Literal["single", "first"]] = ["single", "first"]
    for unwrap in policies:
        with pytest.raises(StopIteration) as excinfo:
            async with unwrap_exception_group(unwrap), anyio.create_task_group():
                raise StopIteration("exhausted") from cause
        assert excinfo.value.__cause__ is cause


@pytest.mark.parametrize("unwrap", ["single", "first"])
async def test_unwrapped_task_error_when_host_is_cancelled(
    unwrap: Literal["single", "first"],
) -> None:
    started = anyio.Event()
    cleaned_up = False

    async def fail() -> None:
        await started.wait()
        await _fail_with_cause()

    async def block() -> None:
        nonlocal cleaned_up
        try:
            started.set()
            await anyio.sleep_forever()
        finally:
            cleaned_up = True

    with pytest.raises(RuntimeError, match="task failed") as excinfo:
        async with unwrap_exception_group(unwrap), anyio.create_task_group() as tg:
            tg.start_soon(fail)
            tg.start_soon(block)
            await anyio.sleep_forever()
    _assert_cause_kept(excinfo.value)
    assert cleaned_up


def _stored_cause(error: BaseException) -> Any:
    return vars(BaseException)["__cause__"].__get__(error)


@dataclasses.dataclass(slots=True)
class _SlottedCauseError(Exception):
    __cause__: BaseException | None = None


def _raise_lookup_error(self: BaseException) -> BaseException | None:
    raise LookupError("getter failed")


_ThrowingCauseError: Any = type(
    "_ThrowingCauseError", (Exception,), {"__cause__": property(_raise_lookup_error)}
)


@pytest.mark.parametrize(
    "error_type", [_SlottedCauseError, _ThrowingCauseError], ids=["slot", "getter"]
)
async def test_unwrapped_task_error_keeps_a_cause_its_class_shadows(
    error_type: Callable[[], BaseException],
) -> None:
    cause = ValueError("cause")
    error = error_type()

    async def fail() -> None:
        raise error from cause

    with pytest.raises(Exception) as excinfo:
        await collect(fail())
    assert excinfo.value is error
    assert _stored_cause(error) is cause

    with pytest.raises(Exception) as excinfo:
        await tg_collect([fail])
    assert excinfo.value is error
    assert _stored_cause(error) is cause


_SpoofedGroupError: Any = type(
    "_SpoofedGroupError", (Exception,), {"__class__": ExceptionGroup}
)
_ThrowingClassError: Any = type(
    "_ThrowingClassError", (Exception,), {"__class__": property(_raise_lookup_error)}
)


@pytest.mark.parametrize(
    "error_type", [_SpoofedGroupError, _ThrowingClassError], ids=["spoofed", "getter"]
)
@pytest.mark.parametrize("unwrap", ["single", "first", None])
async def test_error_that_is_not_a_group_passes_through(
    error_type: Callable[[], BaseException],
    unwrap: Literal["single", "first"] | None,
) -> None:
    error = error_type()

    with pytest.raises(Exception) as excinfo:
        with unwrap_exception_group(unwrap):
            raise error
    assert excinfo.value is error

    with pytest.raises(Exception) as excinfo:
        async with unwrap_exception_group(unwrap):
            raise error
    assert excinfo.value is error
