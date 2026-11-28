"""Worker threads that the merge outlives."""

import threading
from collections.abc import Callable
from typing import BinaryIO, TypeVar

import anyio

T = TypeVar("T")


async def run_owned(work: Callable[[], T]) -> T:
    """Run `work` in a worker thread and return its result; the caller outlives it.

    AnyIO's ``to_thread`` holds off cancel-scope cancellation until its
    thread finishes, but a native asyncio cancellation (``Task.cancel()``, a
    timeout) leaves the await while the thread runs on. A merge that then
    unwound would release its lock and close its sources under a worker
    still writing, which could overwrite what a later merge wrote. So when the await raises, work that has not
    started never runs, and work that has started is waited for, through any
    further cancellations, before the exception is re-raised. A cancel
    scope's cancellation, which ``to_thread`` holds off rather than raises,
    is raised once the work has finished. An exception from `work`
    propagates.
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
    await anyio.lowlevel.checkpoint_if_cancelled()
    return result[0]


class OwnedReads:
    """A source whose reads in another component's worker threads the caller outlives.

    The S3 upload reads its source in AnyIO worker threads, which a native
    asyncio cancellation leaves running. :meth:`release` waits, through any
    cancellations, for a read in progress, and a read that starts after it
    is refused without touching the source, so the caller can close the
    source once it returns.
    """

    def __init__(self, source: BinaryIO) -> None:
        self._source = source
        self._lock = threading.Lock()
        self._reading = 0
        self._released = False
        self._idle = threading.Event()
        self._idle.set()

    def read(self, size: int = -1) -> bytes:
        with self._lock:
            if self._released:
                raise ValueError("The source was released.")
            self._reading += 1
            self._idle.clear()
        try:
            return self._source.read(size)
        finally:
            with self._lock:
                self._reading -= 1
                if not self._reading:
                    self._idle.set()

    async def release(self) -> None:
        """Refuse further reads and wait for any read in progress."""
        with self._lock:
            self._released = True
        await _finish(self._idle)


async def _finish(finished: threading.Event) -> None:
    """Wait for `finished`, through any number of further cancellations."""
    while not finished.is_set():
        try:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(finished.wait)
        except anyio.get_cancelled_exc_class():
            # a further native cancellation; the shield keeps out the others
            pass
