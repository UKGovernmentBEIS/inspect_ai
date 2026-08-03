import gc
import weakref

import anyio.to_thread

from inspect_ai._util._async import run_coroutine


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
