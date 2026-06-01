"""Unit tests for the control server's keep-alive shutdown wait.

These run as *sync* tests driving their own ``asyncio.run`` loop rather
than ``async def`` tests. The repo's anyio test harness wraps async
tests in machinery that itself uses worker threads on the same loop,
which would pollute the thread-leak assertion below; an isolated
``asyncio.run`` keeps the loop ours alone.
"""

import asyncio
import contextlib
import threading


def _worker_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "AnyIO worker thread")


def test_wait_for_shutdown_cancel_leaves_no_blocked_thread() -> None:
    """Cancelling the keep-alive wait must not abandon a blocked worker thread.

    Regression: the wait used to offload ``threading.Event.wait()`` to a
    non-daemon anyio worker thread. On cancellation (Ctrl+C) that thread
    was abandoned still blocked, hanging interpreter shutdown on the join
    and forcing a second Ctrl+C. The wait now awaits a loop-native event,
    so cancellation leaves no thread behind.
    """
    from inspect_ai._control.server import ControlServer, wait_for_shutdown_async

    async def scenario() -> int:
        server = ControlServer(run_id="test")
        before = _worker_threads()
        task = asyncio.ensure_future(wait_for_shutdown_async(server))
        try:
            await asyncio.sleep(0.1)  # let the wait start
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await asyncio.sleep(0.1)  # give any spawned worker time to appear
            return _worker_threads() - before
        finally:
            # Release any abandoned worker so a reintroduced regression
            # fails the assertion instead of hanging the suite at exit.
            server.shutdown_event.set()

    leaked = asyncio.run(scenario())
    assert leaked == 0, f"cancelled shutdown wait leaked {leaked} worker thread(s)"


def test_wait_for_shutdown_returns_when_event_set() -> None:
    """Setting the shutdown event releases the wait promptly."""
    from inspect_ai._control.server import ControlServer, wait_for_shutdown_async

    async def scenario() -> None:
        server = ControlServer(run_id="test")

        async def _set_soon() -> None:
            await asyncio.sleep(0.05)
            server.shutdown_event.set()

        async with asyncio.timeout(5):
            await asyncio.gather(_set_soon(), wait_for_shutdown_async(server))

    asyncio.run(scenario())
