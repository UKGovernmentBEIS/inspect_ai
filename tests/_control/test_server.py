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

        # asyncio.wait_for (not asyncio.timeout, which is 3.11+) keeps this
        # runnable + type-checkable on Python 3.10.
        await asyncio.wait_for(
            asyncio.gather(_set_soon(), wait_for_shutdown_async(server)),
            timeout=5,
        )

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


def test_start_does_not_publish_discovery_when_bind_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A failed UDS bind must not leave a live discovery file behind.

    The socket is bound synchronously in ``start()`` (then handed to uvicorn
    pre-bound), so a bind failure raises before the discovery file is
    written. Regression guard: a live ``<pid>.json`` pointing at a dead
    socket would strand ``inspect ctl`` clients — and under ``--keep-alive``
    the shutdown path can't connect, leaving the process parked forever.
    ``start()`` must raise and write no discovery file; ``control_server``
    must degrade to ``None``.
    """
    import inspect_ai._control.discovery as discovery
    import inspect_ai._control.server as server_mod
    from inspect_ai._control.discovery import list_discovered_servers
    from inspect_ai._control.server import ControlServer, control_server

    def _stub_data_dir(subdir: str | None = None):
        path = (tmp_path / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(discovery, "inspect_data_dir", _stub_data_dir)

    # Force the bind to fail deterministically: an overlong socket path makes
    # sock.bind() raise OSError (ENAMETOOLONG) — a real-world bind failure
    # (cf. a UDS PermissionError) — synchronously inside start(), before the
    # discovery file is written. (A missing parent dir would NOT do it:
    # start() calls prepare_socket_path(), which creates the parent. And
    # relying on the *test* tmp_path being overlong is fragile — it passes for
    # the wrong reason on macOS's long default temp dir and not at all under a
    # short --basetemp.)
    bad_socket = tmp_path / ("ctl-" + "x" * 200 + ".sock")
    monkeypatch.setattr(server_mod, "default_socket_path", lambda _pid: bad_socket)

    async def run() -> None:
        # start() surfaces the bind failure directly...
        server = ControlServer(run_id="run-1")
        with pytest.raises(OSError):
            await server.start()
        assert server._discovery_path is None

        # ...and nothing is published, so no client can find a dead socket.
        assert list_discovered_servers() == []
        assert list(discovery.discovery_dir().glob("*.json")) == []

        # control_server degrades gracefully to "no surface".
        async with control_server(run_id="run-2") as srv:
            assert srv is None
        assert list_discovered_servers() == []

    asyncio.run(run())


async def test_sample_endpoint_addresses_reserved_char_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GET /evals/<id>/sample` reaches ids with URL-reserved characters.

    Sample ids are arbitrary strings — ``case/001`` (path separator),
    ``q?x#y`` (query / fragment delimiters). They ride in the ``sample_id``
    *query parameter* (not a path segment, which can't carry them); the client
    URL-encodes and the server decodes them end to end. A path-segment route
    could never reach these. Pins that the handler receives the id intact.

    A normal ``async def`` test (no isolated ``asyncio.run``): unlike the
    thread-leak tests above, this asserts nothing about worker threads, so the
    anyio harness is fine — and it gets dual-backend coverage for free.
    """
    from inspect_ai._control import server as server_mod

    received: list[tuple[str, str, int]] = []

    async def _echo(eval_id: str, sample_id: str, epoch: int) -> dict[str, object]:
        received.append((eval_id, sample_id, epoch))
        return {"sample_id": sample_id, "epoch": epoch, "status": "completed"}

    monkeypatch.setattr(server_mod, "sample_error_detail", _echo)

    tricky_ids = ["case/001", "q?x#y"]

    app = server_mod.ControlServer(run_id="test")._build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        for sid in tricky_ids:
            # httpx URL-encodes the query param; the route must round-trip it.
            response = await client.get(
                "/evals/ev1/sample", params={"sample_id": sid, "epoch": 1}
            )
            assert response.status_code == 200, (sid, response.text)
            assert response.json()["sample_id"] == sid, sid

    assert received == [("ev1", sid, 1) for sid in tricky_ids], received


def test_control_server_cleans_up_partial_startup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A startup failure *after* bind must not leak the serve task / socket.

    ``start()`` binds the socket and launches the uvicorn serve task BEFORE it
    writes the discovery file. If that write fails (bad dir perms, disk full —
    the write now creates the file via ``os.open`` and can raise), the partial
    server is left running: an ``inspect-ctl-server`` task on the loop plus a
    live socket node. ``control_server`` must tear that down (``stop()``)
    before yielding ``None``, not just swallow the exception.

    Isolated ``asyncio.run`` (not an ``async def`` test) so ``all_tasks()``
    sees only this scenario's tasks, not the anyio harness's.
    """
    import tempfile
    from pathlib import Path

    import inspect_ai._control.discovery as discovery
    from inspect_ai._control import server as server_mod
    from inspect_ai._control.server import control_server

    def _stub_data_dir(subdir: str | None = None) -> Path:
        path = (tmp_path / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(discovery, "inspect_data_dir", _stub_data_dir)

    # A short socket dir so the bind itself succeeds — we want the failure to
    # come from the discovery write, which happens after bind + serve launch.
    sock_dir = Path(tempfile.mkdtemp(prefix="ctl_part_", dir="/tmp"))
    monkeypatch.setattr(
        server_mod, "default_socket_path", lambda pid: sock_dir / f"{pid}.sock"
    )

    def _boom(*args: object, **kwargs: object) -> object:
        raise OSError("simulated discovery write failure")

    monkeypatch.setattr(server_mod, "write_discovery_file", _boom)

    async def scenario() -> list[asyncio.Task[object]]:
        async with control_server(run_id="run-partial") as srv:
            # Bind + serve task launched, then the discovery write blew up —
            # control_server must degrade to None.
            assert srv is None
        # Back outside the context: the partial server must be torn down.
        return [
            t
            for t in asyncio.all_tasks()
            if t.get_name() == "inspect-ctl-server" and not t.done()
        ]

    try:
        leaked = asyncio.run(scenario())
        assert leaked == [], f"leaked uvicorn serve task(s): {leaked}"
        assert list(sock_dir.glob("*.sock")) == [], (
            "socket node leaked after a partial-startup cleanup"
        )
        assert list(tmp_path.rglob("*.json")) == [], "discovery file present"
    finally:
        for p in sock_dir.glob("*"):
            p.unlink(missing_ok=True)
        sock_dir.rmdir()
