import gc
import os
import subprocess
import sys
import textwrap
import threading
import weakref

import anyio.to_thread
import pytest

from inspect_ai._util._async import run_coroutine


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
