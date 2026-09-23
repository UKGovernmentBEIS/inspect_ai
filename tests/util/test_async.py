import gc
import os
import subprocess
import sys
import textwrap
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

    async def make_payload() -> Payload:
        await anyio.to_thread.run_sync(lambda: None)
        return Payload()

    result = run_coroutine(make_payload())
    ref = weakref.ref(result)
    del result
    gc.collect()
    assert ref() is None, "result still referenced after release"
