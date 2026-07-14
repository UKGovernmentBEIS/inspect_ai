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
    from inspect_ai._control.server import (
        ControlServer,
        request_keep_alive,
        reset_keep_alive,
        wait_for_shutdown_async,
    )

    async def scenario() -> int:
        server = ControlServer(run_id="test")
        request_keep_alive()  # so the park actually blocks
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
            reset_keep_alive()

    leaked = asyncio.run(scenario())
    assert leaked == 0, f"cancelled shutdown wait leaked {leaked} worker thread(s)"


def test_stop_reraises_cancellation_without_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Ctrl-C teardown must not log "did not shut down cleanly".

    Regression: on Ctrl-C the eval's cancel scope tears down both the uvicorn
    serve task and the ``stop()`` drain together, so ``asyncio.wait_for`` raises
    ``CancelledError``. The drain used to catch that alongside ``Exception`` and
    log a misleading ``Control server did not shut down cleanly`` warning (and
    swallow the cancellation). ``stop()`` must instead re-raise the
    cancellation, log nothing, and still run its discovery/socket cleanup.
    """
    import logging

    from inspect_ai._control.server import ControlServer

    class _StubUvicorn:
        def __init__(self) -> None:
            self.should_exit = False

    async def scenario() -> bool:
        server = ControlServer(run_id="test")
        server._uvicorn_server = _StubUvicorn()
        # A stand-in for uvicorn's serve task that never drains on its own, so
        # the only way out of the drain's wait_for is the outer cancellation.
        serve_task: asyncio.Task[None] = asyncio.ensure_future(asyncio.sleep(3600))
        server._serve_task = serve_task

        cleaned_up = False

        async def _stop_and_track() -> None:
            nonlocal cleaned_up
            try:
                await server.stop()
            finally:
                # stop()'s own finally must have run its cleanup before the
                # cancellation propagates out of it.
                cleaned_up = serve_task.cancelled() or serve_task.done()

        stop_task = asyncio.ensure_future(_stop_and_track())
        await asyncio.sleep(0.1)  # let stop() reach its wait_for
        stop_task.cancel()  # simulate the eval cancel scope tearing down
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task
        # the cancellation must have propagated (stop did not swallow it)...
        assert stop_task.cancelled()
        return cleaned_up

    with caplog.at_level(logging.WARNING, logger="inspect_ai._control.server"):
        cleaned_up = asyncio.run(scenario())

    assert cleaned_up, "stop() must still tear down the serve task on cancellation"
    assert "did not shut down cleanly" not in caplog.text


def test_wait_for_shutdown_returns_when_released() -> None:
    """Releasing keep-alive (POST /release) wakes the park promptly."""
    from inspect_ai._control.server import (
        ControlServer,
        request_keep_alive,
        request_release,
        reset_keep_alive,
        wait_for_shutdown_async,
    )

    async def scenario() -> None:
        server = ControlServer(run_id="test")
        request_keep_alive()

        async def _release_soon() -> None:
            await asyncio.sleep(0.05)
            request_release()
            await server.notify_park_change()

        # asyncio.wait_for (not asyncio.timeout, which is 3.11+) keeps this
        # runnable + type-checkable on Python 3.10.
        try:
            await asyncio.wait_for(
                asyncio.gather(_release_soon(), wait_for_shutdown_async(server)),
                timeout=5,
            )
        finally:
            reset_keep_alive()

    asyncio.run(scenario())


def test_endpoint_error_becomes_structured_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exception in an endpoint is converted to a client-displayable error.

    The endpoint handlers let errors propagate; the app-level handler
    turns them into a ``500`` with a ``{"error": ...}`` body (carrying the
    exception type + message) rather than a bare 500, so the CLI/agent can
    show the cause.
    """
    from inspect_ai._control import server as server_mod

    async def _boom(*args: object, **kwargs: object) -> list:
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


async def test_samples_endpoint_parses_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GET /evals/<id>/samples` parses `filter` and defaults it off.

    The state-layer filtering is unit-tested; this pins the route wiring —
    `filter=errors` reaches the state layer as "errors", an omitted param
    keeps the full listing (None), and an unrecognized filter value is
    rejected (422) rather than silently answered with the full listing,
    since the CLI trusts the filter was applied and keeps no fallback.
    """
    from inspect_ai._control import server as server_mod

    seen: dict[str, object] = {}

    async def _fake(
        eval_id: str,
        active_since: float | None = None,
        sample_filter: str | None = None,
    ) -> list[dict[str, object]]:
        seen["eval_id"] = eval_id
        seen["sample_filter"] = sample_filter
        return []

    monkeypatch.setattr(server_mod, "current_sample_summaries", _fake)

    app = server_mod.ControlServer(run_id="test")._build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        filtered = await client.get("/evals/e1/samples", params={"filter": "errors"})
        assert filtered.status_code == 200, filtered.text
        assert seen["sample_filter"] == "errors"

        default = await client.get("/evals/e1/samples")
        assert default.status_code == 200, default.text
        assert seen["sample_filter"] is None

        seen.clear()
        unknown = await client.get("/evals/e1/samples", params={"filter": "bogus"})
        assert unknown.status_code == 422, unknown.text
        assert "sample_filter" not in seen  # rejected before the state layer


async def test_404_body_shape_distinguishes_missing_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler 404s carry ``{"error": ...}``; the router's 404 does not.

    The CLI reads this distinction (`_handler_404`) to report version skew
    definitively when a route doesn't exist on an older server — see the
    convention comment in ``_build_app``. A handler 404 that dropped the
    ``error`` key would misreport an entity-not-found as version skew.
    """
    from inspect_ai._cli.ctl import _handler_404
    from inspect_ai._control import server as server_mod

    monkeypatch.setattr(server_mod, "cancel_task", lambda task_id, dry_run=False: None)

    app = server_mod.ControlServer(run_id="test")._build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        handler = await client.post("/tasks/nope/cancel")
        assert handler.status_code == 404
        assert _handler_404(handler)

        router = await client.post("/tasks/nope/endpoint-from-the-future")
        assert router.status_code == 404
        assert not _handler_404(router)


def test_resolve_ctl_server_values() -> None:
    """The ``ctl_server`` param resolves to ``(enabled, keep_alive)``.

    ``None`` and ``True`` are the default-on shape, ``False`` disables,
    ``"keep"`` enables + parks. The CLI string spellings are accepted
    case-insensitively so programmatic callers can forward a flag or
    ``INSPECT_EVAL_CTL_SERVER`` env value verbatim. Any other string is
    rejected rather than silently treated as ``True`` — it's more likely a
    typo of ``keep``, and dropping the requested park would strand the
    user.
    """
    from inspect_ai._control.server import resolve_ctl_server
    from inspect_ai._util.error import PrerequisiteError

    assert resolve_ctl_server(None) == (True, False)
    assert resolve_ctl_server(True) == (True, False)
    assert resolve_ctl_server(False) == (False, False)
    assert resolve_ctl_server("keep") == (True, True)
    # `keep-alive` is still accepted as a legacy alias for `keep`
    assert resolve_ctl_server("keep-alive") == (True, True)

    # CLI / env-var spellings forwarded verbatim
    assert resolve_ctl_server("true") == (True, False)
    assert resolve_ctl_server("yes") == (True, False)
    assert resolve_ctl_server("1") == (True, False)
    assert resolve_ctl_server("false") == (False, False)
    assert resolve_ctl_server("no") == (False, False)
    assert resolve_ctl_server("0") == (False, False)
    assert resolve_ctl_server("TRUE") == (True, False)
    assert resolve_ctl_server("KEEP") == (True, True)
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


def test_release_before_park_skips_it() -> None:
    """A release received while the eval is still running means "exit when done".

    The intent is process-wide: the standalone park's wait must return
    immediately, and the eval-set park — which binds a FRESH server after the
    run's server is gone — must see it too. The intent resets at the outermost
    run boundary so a prior run's release can't leak into the next run's park.
    """
    from inspect_ai._control.server import (
        ControlServer,
        keep_alive_intent,
        request_keep_alive,
        request_release,
        reset_keep_alive,
        wait_for_shutdown_async,
    )

    reset_keep_alive()
    try:
        # a mid-run release wins the last word over an earlier keep...
        request_keep_alive()
        request_release()
        assert keep_alive_intent() is False

        # ...so a later park's wait returns immediately, even on a fresh
        # server (the eval-set park shape)
        async def park() -> None:
            await asyncio.wait_for(
                wait_for_shutdown_async(ControlServer(run_id="fresh")), timeout=5
            )

        asyncio.run(park())
    finally:
        reset_keep_alive()


def test_keep_after_release_rearms_the_park() -> None:
    """A keep -> release -> keep while running leaves the process parking.

    The regression: release used to latch irreversibly, so a keep that
    followed it was ignored. Now the intent is last-write-wins and the park
    re-checks it, so the final keep re-arms the park — it blocks until a
    *subsequent* release.
    """
    from inspect_ai._control.server import (
        ControlServer,
        keep_alive_intent,
        request_keep_alive,
        request_release,
        reset_keep_alive,
        wait_for_shutdown_async,
    )

    reset_keep_alive()
    try:

        async def scenario() -> None:
            server = ControlServer(run_id="test")
            request_keep_alive()
            request_release()
            request_keep_alive()  # last write wins
            assert keep_alive_intent() is True

            park = asyncio.ensure_future(wait_for_shutdown_async(server))
            await asyncio.sleep(0.1)
            assert not park.done()  # still parked, despite the earlier release

            # a fresh release now wakes it
            request_release()
            await server.notify_park_change()
            await asyncio.wait_for(park, timeout=5)

        asyncio.run(scenario())
    finally:
        reset_keep_alive()


async def test_release_route_clears_the_intent() -> None:
    """POST /release latches keep-alive off process-wide."""
    from inspect_ai._control.server import (
        ControlServer,
        keep_alive_intent,
        request_keep_alive,
        reset_keep_alive,
    )

    reset_keep_alive()
    try:
        request_keep_alive()
        server = ControlServer(run_id="test")
        app = server._build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            response = await client.post("/release")
            assert response.status_code == 200

        assert keep_alive_intent() is False
    finally:
        reset_keep_alive()


def test_eval_set_park_skipped_when_intent_off() -> None:
    """An off intent makes the eval-set park return without binding.

    The eval-set park binds a fresh server, so the module-level intent is the
    only carrier of a release received during the run. A regression here would
    bind a real control server and park forever — bounded by the wait_for
    timeout.
    """
    from inspect_ai._control.server import request_release, reset_keep_alive
    from inspect_ai._eval.evalset import _keep_alive_park

    reset_keep_alive()
    try:
        request_release()  # intent off
        asyncio.run(asyncio.wait_for(_keep_alive_park("set-1"), timeout=5))
    finally:
        reset_keep_alive()


def test_keep_alive_intent_last_write_wins() -> None:
    """Keep / release toggle a single intent; the last call wins."""
    from inspect_ai._control.server import (
        keep_alive_intent,
        request_keep_alive,
        request_release,
        reset_keep_alive,
    )

    reset_keep_alive()
    try:
        assert keep_alive_intent() is False  # default
        request_keep_alive()
        assert keep_alive_intent() is True
        request_release()
        assert keep_alive_intent() is False
        request_keep_alive()
        assert keep_alive_intent() is True  # a later keep overrides the release
    finally:
        reset_keep_alive()


async def test_keep_route_sets_the_intent() -> None:
    """POST /keep latches keep-alive on process-wide."""
    from inspect_ai._control.server import (
        ControlServer,
        keep_alive_intent,
        reset_keep_alive,
    )

    reset_keep_alive()
    try:
        server = ControlServer(run_id="test")
        app = server._build_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            response = await client.post("/keep")
            assert response.status_code == 200

        assert keep_alive_intent() is True
    finally:
        reset_keep_alive()


async def test_tasks_endpoint_decorates_keep_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /tasks stamps each task summary with the live keep-alive status."""
    from inspect_ai._control import server as server_mod
    from inspect_ai._control.server import (
        ControlServer,
        request_keep_alive,
        reset_keep_alive,
    )

    async def _two_rows(started_at: float) -> list[dict]:
        return [{"task_id": "a"}, {"task_id": "b"}]

    monkeypatch.setattr(server_mod, "current_eval_summaries", _two_rows)

    reset_keep_alive()
    try:

        async def _get() -> list[dict]:
            app = ControlServer(run_id="test")._build_app()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost"
            ) as client:
                return (await client.get("/tasks")).json()

        # off by default
        rows = await _get()
        assert [r["keep_alive"] for r in rows] == [False, False]

        # flips on for every row once keep-alive is latched
        request_keep_alive()
        rows = await _get()
        assert [r["keep_alive"] for r in rows] == [True, True]
    finally:
        reset_keep_alive()


def test_keep_alive_intent_resets() -> None:
    """The keep-alive intent clears at the outermost run boundary."""
    from inspect_ai._control.server import (
        keep_alive_intent,
        request_keep_alive,
        reset_keep_alive,
    )

    reset_keep_alive()
    try:
        assert not keep_alive_intent()
        request_keep_alive()
        assert keep_alive_intent()
        reset_keep_alive()
        assert not keep_alive_intent()
    finally:
        reset_keep_alive()


async def test_tasks_rows_advertise_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every `/tasks` row is stamped with the server's control-API version.

    The version rides the row (like `keep_alive`) so HTTP consumers can gate
    version-dependent requests without an extra round trip; the discovery
    file carries the same value for the window before any task registers.
    """
    from inspect_ai._control import CONTROL_API_VERSION
    from inspect_ai._control import server as server_mod
    from inspect_ai._control.server import ControlServer

    async def _two_rows(started_at: float) -> list[dict]:
        return [{"task_id": "a"}, {"task_id": "b"}]

    monkeypatch.setattr(server_mod, "current_eval_summaries", _two_rows)

    app = ControlServer(run_id="test")._build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rows = (await client.get("/tasks")).json()
    assert [r["api_version"] for r in rows] == [CONTROL_API_VERSION] * 2


def test_start_advertises_api_version_in_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The discovery file published by `start()` carries CONTROL_API_VERSION.

    The CLI gates version-dependent config knobs on the discovery file's
    `api_version` before sending a mutation, so it must be published at bind
    time — including the window before any task registers, when `/tasks` is
    still empty.
    """
    import shutil
    import tempfile
    from pathlib import Path

    import inspect_ai._control.discovery as discovery
    from inspect_ai._control import CONTROL_API_VERSION
    from inspect_ai._control.discovery import list_discovered_servers
    from inspect_ai._control.server import ControlServer

    # short dir under /tmp: macOS pytest tmp_path blows past the AF_UNIX
    # 104-char socket-path limit (cf. the short_data_dir fixture in
    # test_eval_set_integration.py)
    dirpath = Path(tempfile.mkdtemp(prefix="ctl_ver_", dir="/tmp"))

    def _stub_data_dir(subdir: str | None = None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(discovery, "inspect_data_dir", _stub_data_dir)

    async def run() -> None:
        server = ControlServer(run_id="run-1")
        await server.start()
        try:
            assert [s.api_version for s in list_discovered_servers()] == [
                CONTROL_API_VERSION
            ]
        finally:
            await server.stop()

    try:
        asyncio.run(run())
    finally:
        shutil.rmtree(dirpath, ignore_errors=True)
