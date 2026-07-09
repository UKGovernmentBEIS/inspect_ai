"""Tests for the control-channel log-buffer directives.

Covers the directive functions in ``inspect_ai._control.buffer`` (task-keyed,
resolved to the latest attempt's ``EvalState.live``), the server routes that
wrap them (``POST /tasks/<id>/log-flush``; the buffer params ride the
``/tasks/<id>/config`` routes), and the CLI rendering helper.
"""

import asyncio

import httpx
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai._control.buffer import flush_task_samples, task_buffer_config
from inspect_ai._control.eval_state import (
    BufferConfig,
    clear_all_eval_states,
    detach_eval_live,
    register_eval,
)


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    yield
    clear_all_eval_states()


# ---------------------------------------------------------------------------
# Directive functions
# ---------------------------------------------------------------------------


async def test_flush_directive_invokes_provider() -> None:
    calls = {"n": 0}

    async def _flush() -> int:
        calls["n"] += 1
        return 3

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=_flush))

    result = await flush_task_samples("t1")
    assert result == {"flushed": 3}
    assert calls["n"] == 1


async def test_flush_directive_none_when_task_missing() -> None:
    assert await flush_task_samples("nope") is None
    assert await flush_task_samples("") is None


async def test_flush_directive_none_when_no_provider() -> None:
    # a reused/synthetic eval registers without a flush provider
    register_eval("e1", 5, task_id="t1")
    assert await flush_task_samples("t1") is None


async def test_flush_directive_none_after_detach() -> None:
    async def _flush() -> int:
        return 1

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=_flush))
    detach_eval_live("e1")  # retry detaches the live data source
    assert await flush_task_samples("t1") is None


async def test_flush_directive_resolves_latest_attempt() -> None:
    """A retry registers a fresh attempt; the task-keyed flush follows it."""
    calls = {"old": 0, "new": 0}

    async def _old() -> int:
        calls["old"] += 1
        return 0

    async def _new() -> int:
        calls["new"] += 1
        return 2

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=_old))
    detach_eval_live("e1")  # superseded on retry
    register_eval("e2", 5, task_id="t1", live=FakeLiveEvalData(flush=_new))

    result = await flush_task_samples("t1")
    assert result == {"flushed": 2}
    assert calls == {"old": 0, "new": 1}


def test_buffer_directive_read_only() -> None:
    seen: list[tuple[int | None, int | None]] = []

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        seen.append((log_buffer, log_shared))
        return BufferConfig(log_buffer=10, pending=2, log_shared=30)

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(buffer=_buffer))

    result = task_buffer_config("t1")
    assert result == {"log_buffer": 10, "pending": 2, "log_shared": 30}
    # a pure read passes (None, None) — no mutation
    assert seen == [(None, None)]


def test_buffer_directive_set_values() -> None:
    state = {"log_buffer": 10, "log_shared": 30}

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        if log_buffer is not None:
            state["log_buffer"] = log_buffer
        if log_shared is not None:
            state["log_shared"] = log_shared
        return BufferConfig(
            log_buffer=state["log_buffer"], pending=0, log_shared=state["log_shared"]
        )

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(buffer=_buffer))

    result = task_buffer_config("t1", log_buffer=3, log_shared=None)
    assert result == {"log_buffer": 3, "pending": 0, "log_shared": 30}
    # the unset param is left untouched
    assert state == {"log_buffer": 3, "log_shared": 30}


def test_buffer_directive_none_when_missing() -> None:
    assert task_buffer_config("nope") is None
    register_eval("e1", 5, task_id="t1")  # no buffer provider
    assert task_buffer_config("t1") is None


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------


def _app():
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_log_flush_route_ok_and_404() -> None:
    async def _flush() -> int:
        return 4

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=_flush))

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post("/tasks/t1/log-flush")
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"flushed": 4}

        missing = await client.post("/tasks/missing/log-flush")
        assert missing.status_code == 404


async def test_buffer_params_ride_config_routes() -> None:
    current = BufferConfig(log_buffer=10, pending=1, log_shared=None)

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        nonlocal current
        current = current._replace(
            log_buffer=log_buffer if log_buffer is not None else current.log_buffer,
            log_shared=log_shared if log_shared is not None else current.log_shared,
        )
        return current

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(buffer=_buffer))

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        got = await client.get("/tasks/t1/config")
        assert got.status_code == 200, got.text
        assert got.json()["buffer"] == {
            "log_buffer": 10,
            "pending": 1,
            "log_shared": None,
        }

        patched = await client.patch("/tasks/t1/config", params={"log_buffer": 2})
        assert patched.status_code == 200, patched.text
        assert patched.json()["buffer"]["log_buffer"] == 2
        assert patched.json()["requested"] == {"log_buffer": 2}
        assert current.log_buffer == 2

        # dry_run reports the request without applying it
        dry = await client.patch(
            "/tasks/t1/config", params={"log_buffer": 9, "dry_run": True}
        )
        assert dry.status_code == 200, dry.text
        assert dry.json()["requested"] == {"log_buffer": 9}
        assert current.log_buffer == 2

        # a task with no live buffer reports the knobs as absent (not a 404)
        register_eval("e2", 5, task_id="t2")
        bare = await client.get("/tasks/t2/config")
        assert bare.status_code == 200, bare.text
        assert bare.json()["buffer"] is None

        # ...and an explicit set against it warns like the other unadjustable
        # knobs rather than silently no-opping
        noop = await client.patch("/tasks/t2/config", params={"log_buffer": 2})
        assert noop.status_code == 200, noop.text
        assert noop.json()["requested"] == {"log_buffer": 2}
        assert any("log_buffer" in w for w in noop.json()["warnings"])

        missing = await client.get("/tasks/missing/config")
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def test_print_config_renders_buffer_knobs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The buffer params (absorbed into `ctl config`) render as task knobs."""
    from inspect_ai._cli.ctl import _print_config

    def _knobs(log_buffer: int, pending: int, log_shared: int | None) -> dict:
        return {
            "max_sandboxes": {"scope": "process", "providers": []},
            "max_connections": {"scope": "process", "adaptive": []},
            "log_buffer": {"scope": "task", "value": log_buffer, "pending": pending},
            "log_shared": {"scope": "task", "value": log_shared},
        }

    _print_config(
        {
            "dry_run": False,
            "knobs": _knobs(7, 3, 30),
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "config:" in out
    assert "7 samples" in out
    assert "(3 pending)" in out
    assert "30s" in out

    _print_config(
        {
            "dry_run": False,
            "knobs": _knobs(1, 0, None),
            "requested": {"log_buffer": 1},
            "warnings": [],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "updated config:" in out
    assert "shared sync [task]:      off" in out


def test_log_flush_route_error_becomes_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider exception surfaces as the structured 500 (not a bare crash)."""
    from inspect_ai._control import server as server_mod

    async def _boom() -> int:
        raise RuntimeError("disk full")

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=_boom))

    async def scenario() -> httpx.Response:
        app = server_mod.ControlServer(run_id="test")._build_app()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            return await client.post("/tasks/t1/log-flush")

    response = asyncio.run(scenario())
    assert response.status_code == 500
    assert "disk full" in response.json()["error"]


async def test_log_shared_set_without_sync_warns() -> None:
    """A log_shared set the buffer ignores (no shared sync) warns, not no-ops.

    `buffer_config` reports the resulting view only, so a syncless buffer
    echoes `log_shared: None` after the request — the server must turn that
    into a not-adjustable warning like the other knobs.
    """

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        # a buffer with no shared-log sync: log_shared sets are ignored
        return BufferConfig(log_buffer=10, pending=0, log_shared=None)

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(buffer=_buffer))

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        patched = await client.patch("/tasks/t1/config", params={"log_shared": 30})
        assert patched.status_code == 200, patched.text
        assert patched.json()["requested"] == {"log_shared": 30}
        assert any(
            "log_shared is not adjustable" in w for w in patched.json()["warnings"]
        )

        # dry-run reports the same rejection
        dry = await client.patch(
            "/tasks/t1/config", params={"log_shared": 30, "dry_run": True}
        )
        assert any("log_shared is not adjustable" in w for w in dry.json()["warnings"])

        # a log_shared set that lands (sync running) does not warn
        def _synced(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
            return BufferConfig(log_buffer=10, pending=0, log_shared=log_shared or 60)

        register_eval("e2", 5, task_id="t2", live=FakeLiveEvalData(buffer=_synced))
        ok = await client.patch("/tasks/t2/config", params={"log_shared": 30})
        assert not any("log_shared" in w for w in ok.json()["warnings"])
