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

import httpx
import pytest


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


def test_endpoint_error_becomes_structured_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception in an endpoint is converted to a client-displayable error.

    The endpoint handlers let errors propagate; the app-level handler
    turns them into a ``500`` with a ``{"error": ...}`` body (carrying the
    exception type + message) rather than a bare 500, so the CLI/agent can
    show the cause.
    """
    from inspect_ai._control import server as server_mod

    async def _boom(eval_id: str) -> list:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(server_mod, "current_sample_summaries", _boom)

    async def scenario() -> httpx.Response:
        app = server_mod.ControlServer(run_id="test")._build_app()
        # raise_app_exceptions=False models the real client's view: Starlette
        # sends our 500 response, then re-raises for server-side logging
        # (which uvicorn handles in production); we want the response.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            return await client.get("/evals/abc/samples")

    response = asyncio.run(scenario())
    assert response.status_code == 500
    error = response.json()["error"]
    assert "RuntimeError" in error and "kaboom" in error


def test_error_detail_prefers_server_body() -> None:
    """The CLI surfaces the server's ``{"error": ...}`` over the bare HTTP error."""
    from inspect_ai._cli.ctl import _error_detail

    request = httpx.Request("GET", "http://localhost/evals/x/samples")
    response = httpx.Response(
        500, json={"error": "RuntimeError: kaboom"}, request=request
    )
    status_error = httpx.HTTPStatusError("500", request=request, response=response)
    assert _error_detail(status_error) == "RuntimeError: kaboom"

    # No response attached → fall back to the exception string.
    assert "plain failure" in _error_detail(OSError("plain failure"))
