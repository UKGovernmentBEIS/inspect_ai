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

    async def _boom(eval_id: str, active_since: float | None = None) -> list:
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
    socket would strand ``inspect ctl`` clients — and under a keep-alive
    park the shutdown path can't connect, leaving the process parked forever.
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


async def test_sample_events_endpoint_parses_type_and_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample-events route parses `type`, round-trips a reserved id, 404s.

    `GET /evals/<id>/sample/events`: comma-split `type` filter, `sample_id` as a
    query param (so reserved chars address), and a missing sample → 404. The
    state-layer logic is integration-tested; this pins the route wiring.
    """
    from inspect_ai._control import server as server_mod

    seen: dict[str, object] = {}

    async def _fake(
        eval_id: str,
        sample_id: str,
        epoch: int,
        *,
        since: object,
        tail: object,
        types: object,
        full: object,
        since_time: object,
        until: object,
    ) -> dict[str, object] | None:
        seen["sample_id"] = sample_id
        seen["types"] = types
        seen["full"] = full
        if sample_id == "missing":
            return None
        return {"events": [], "next": "c", "done": True}

    monkeypatch.setattr(server_mod, "sample_events", _fake)

    app = server_mod.ControlServer(run_id="test")._build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.get(
            "/evals/e1/sample/events",
            params={"sample_id": "case/001", "type": "model,tool", "full": "true"},
        )
        assert ok.status_code == 200, ok.text
        assert seen["sample_id"] == "case/001"  # reserved-char id round-trips
        assert seen["types"] == frozenset({"model", "tool"})  # comma-split
        assert seen["full"] is True

        # whitespace around members is stripped — `--type "model, tool"`
        # must not silently filter everything out
        spaced = await client.get(
            "/evals/e1/sample/events",
            params={"sample_id": "case/001", "type": " model , tool, "},
        )
        assert spaced.status_code == 200, spaced.text
        assert seen["types"] == frozenset({"model", "tool"})

        missing = await client.get(
            "/evals/e1/sample/events", params={"sample_id": "missing"}
        )
        assert missing.status_code == 404


def test_resolve_ctl_server_values() -> None:
    """The ``ctl_server`` param resolves to ``(enabled, keep_alive)``.

    ``None`` and ``True`` are the default-on shape, ``False`` disables,
    ``"keep-alive"`` enables + parks. The CLI string spellings are accepted
    case-insensitively so programmatic callers can forward a flag or
    ``INSPECT_EVAL_CTL_SERVER`` env value verbatim. Any other string is
    rejected rather than silently treated as ``True`` — it's more likely a
    typo of ``keep-alive``, and dropping the requested park would strand the
    user.
    """
    from inspect_ai._control.server import resolve_ctl_server
    from inspect_ai._util.error import PrerequisiteError

    assert resolve_ctl_server(None) == (True, False)
    assert resolve_ctl_server(True) == (True, False)
    assert resolve_ctl_server(False) == (False, False)
    assert resolve_ctl_server("keep-alive") == (True, True)

    # CLI / env-var spellings forwarded verbatim
    assert resolve_ctl_server("true") == (True, False)
    assert resolve_ctl_server("yes") == (True, False)
    assert resolve_ctl_server("1") == (True, False)
    assert resolve_ctl_server("false") == (False, False)
    assert resolve_ctl_server("no") == (False, False)
    assert resolve_ctl_server("0") == (False, False)
    assert resolve_ctl_server("TRUE") == (True, False)
    assert resolve_ctl_server("Keep-Alive") == (True, True)

    with pytest.raises(PrerequisiteError, match="keepalive"):
        resolve_ctl_server("keepalive")


def test_control_server_disabled_binds_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``enabled=False`` (the ``--ctl-server=false`` path) skips the bind.

    Yields ``None`` and publishes no discovery file — nothing for
    ``inspect ctl`` to find.
    """
    import inspect_ai._control.discovery as discovery
    from inspect_ai._control.discovery import list_discovered_servers
    from inspect_ai._control.server import control_server

    def _stub_data_dir(subdir: str | None = None):
        path = (tmp_path / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(discovery, "inspect_data_dir", _stub_data_dir)

    async def run() -> None:
        async with control_server(run_id="run-off", enabled=False) as srv:
            assert srv is None
            assert list_discovered_servers() == []
            assert list(discovery.discovery_dir().glob("*")) == []

    asyncio.run(run())


def test_release_latches_before_the_park() -> None:
    """A release received while the eval is still running means "exit when done".

    The route latches process-wide (not just the per-server event): the
    standalone park's wait must return immediately, and the eval-set park —
    which binds a FRESH server after the run's server is gone — must see the
    latch too. The latch resets at the outermost run boundary so a prior
    run's release can't leak into the next run's park.
    """
    from inspect_ai._control.server import (
        ControlServer,
        release_requested,
        request_release,
        reset_release_requested,
        wait_for_shutdown_async,
    )

    reset_release_requested()
    try:
        assert not release_requested()

        # mid-run release latches...
        request_release()
        assert release_requested()

        # ...so a later park's wait returns immediately, even on a fresh
        # server whose own event was never set (the eval-set park shape)
        async def park() -> None:
            await asyncio.wait_for(
                wait_for_shutdown_async(ControlServer(run_id="fresh")), timeout=5
            )

        asyncio.run(park())

        # the next run clears the latch
        reset_release_requested()
        assert not release_requested()
    finally:
        reset_release_requested()


async def test_release_route_sets_the_latch() -> None:
    """POST /release latches process-wide in addition to the server event."""
    from inspect_ai._control.server import (
        ControlServer,
        release_requested,
        reset_release_requested,
    )

    reset_release_requested()
    try:
        server = ControlServer(run_id="test")
        app = server._build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            response = await client.post("/release")
            assert response.status_code == 200

        assert release_requested()
        assert server.shutdown_event.is_set()
    finally:
        reset_release_requested()


def test_eval_set_park_skipped_when_release_latched() -> None:
    """A latched release makes the eval-set park return without binding.

    The eval-set park binds a fresh server (fresh event), so the latch is
    the only carrier of a release received during the run. A regression
    here would bind a real control server and park forever — bounded by
    the wait_for timeout.
    """
    from inspect_ai._control.server import request_release, reset_release_requested
    from inspect_ai._eval.evalset import _keep_alive_park

    reset_release_requested()
    try:
        request_release()
        asyncio.run(asyncio.wait_for(_keep_alive_park("set-1"), timeout=5))
    finally:
        reset_release_requested()


async def test_add_eval_route_409_without_controller() -> None:
    """`POST /evals` is rejected when the run isn't accepting added tasks."""
    from inspect_ai._control import server as server_mod
    from inspect_ai._control.run_control import clear_run_controller

    clear_run_controller()  # no addable run registered (not --ctl-server=keep-alive)
    app = server_mod.ControlServer(run_id="test")._build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        r = await client.post("/evals", json={"task": "t"})
    assert r.status_code == 409
    assert "keep-alive" in r.json()["error"]


async def test_add_eval_route_accepts_and_reports() -> None:
    """`POST /evals` resolves + queues a task and returns the add report."""
    from inspect_ai._control import server as server_mod
    from inspect_ai._control.run_control import (
        clear_run_controller,
        create_run_controller,
        register_run_controller,
    )

    sentinel = object()

    def resolve(task: str, task_args: object, model: object) -> object:
        return [sentinel], {
            "task": task,
            "tasks": [{"task_id": "x", "task": task, "dataset_samples": 2}],
        }

    controller = create_run_controller("test", resolve)
    register_run_controller(controller)
    try:
        app = server_mod.ControlServer(run_id="test")._build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            r = await client.post(
                "/evals", json={"task": "mytask", "task_args": {"a": 1}}
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["accepted"] is True and body["task"] == "mytask"
        # the route queued the resolved batch for the park
        batch = await controller.next_pending()
        assert batch == [sentinel]
    finally:
        clear_run_controller()


async def test_add_eval_route_400_on_unresolvable_spec() -> None:
    """A spec that can't be resolved is a 400 carrying the resolver's message."""
    from inspect_ai._control import server as server_mod
    from inspect_ai._control.run_control import (
        clear_run_controller,
        create_run_controller,
        register_run_controller,
    )

    def resolve(task: str, task_args: object, model: object) -> object:
        raise ValueError(f"No task found for '{task}'.")

    register_run_controller(create_run_controller("test", resolve))
    try:
        app = server_mod.ControlServer(run_id="test")._build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            r = await client.post("/evals", json={"task": "nope"})
        assert r.status_code == 400
        assert "No task found" in r.json()["error"]
    finally:
        clear_run_controller()
