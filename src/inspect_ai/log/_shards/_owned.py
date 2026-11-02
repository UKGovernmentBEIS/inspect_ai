"""Worker threads that the merge and its deletion outlive."""

import threading
from collections.abc import Callable
from typing import TypeVar

import anyio

T = TypeVar("T")


async def run_owned(work: Callable[[], T]) -> T:
    """Run `work` in a worker thread and return its result; the caller outlives it.

    AnyIO's ``to_thread`` holds off cancel-scope cancellation until its
    thread finishes, but a native asyncio cancellation (``Task.cancel()``, a
    timeout) leaves the await while the thread runs on. A merge or deletion
    that then unwound would release its lock and close its sources under a
    worker still writing or deleting, which could overwrite or delete what a
    later operation wrote. So when the await raises, work that has not
    started never runs, and work that has started is waited for, through any
    further cancellations, before the exception is re-raised. An exception
    from `work` propagates.
    """
    lock = threading.Lock()
    finished = threading.Event()
    state = {"started": False, "abandoned": False}
    result: list[T] = []

    def run() -> None:
        with lock:
            if state["abandoned"]:
                return
            state["started"] = True
        try:
            result.append(work())
        finally:
            finished.set()

    try:
        await anyio.to_thread.run_sync(run)
    except BaseException:
        with lock:
            state["abandoned"] = True
            started = state["started"]
        if started:
            await _finish(finished)
        raise
    return result[0]


async def _finish(finished: threading.Event) -> None:
    """Wait for `finished`, through any number of further cancellations."""
    while not finished.is_set():
        try:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(finished.wait)
        except anyio.get_cancelled_exc_class():
            # a further native cancellation; the shield keeps out the others
            pass
