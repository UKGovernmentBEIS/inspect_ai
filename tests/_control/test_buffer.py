"""Tests for the control-channel buffer directives: ``flush`` and ``buffer``.

Covers the directive functions in ``inspect_ai._control.buffer`` (resolved
through the process-global ``EvalState`` providers), the server routes that wrap
them, and the CLI rendering helper.
"""

import asyncio

import httpx
import pytest

from inspect_ai._control.buffer import eval_buffer_config, flush_eval_samples
from inspect_ai._control.eval_state import (
    BufferConfig,
    clear_all_eval_states,
    detach_eval_providers,
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

    register_eval("e1", 5, flush_provider=_flush)

    result = await flush_eval_samples("e1")
    assert result == {"flushed": 3}
    assert calls["n"] == 1


async def test_flush_directive_none_when_eval_missing() -> None:
    assert await flush_eval_samples("nope") is None


async def test_flush_directive_none_when_no_provider() -> None:
    # a reused/synthetic eval registers without a flush provider
    register_eval("e1", 5)
    assert await flush_eval_samples("e1") is None


async def test_flush_directive_none_after_detach() -> None:
    async def _flush() -> int:
        return 1

    register_eval("e1", 5, flush_provider=_flush)
    detach_eval_providers("e1")  # retry detaches the live providers
    assert await flush_eval_samples("e1") is None


async def test_buffer_directive_read_only() -> None:
    seen: list[tuple[int | None, int | None]] = []

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        seen.append((log_buffer, log_shared))
        return BufferConfig(log_buffer=10, pending=2, log_shared=30)

    register_eval("e1", 5, buffer_provider=_buffer)

    result = await eval_buffer_config("e1")
    assert result == {"log_buffer": 10, "pending": 2, "log_shared": 30}
    # a pure read passes (None, None) — no mutation
    assert seen == [(None, None)]


async def test_buffer_directive_set_values() -> None:
    state = {"log_buffer": 10, "log_shared": 30}

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        if log_buffer is not None:
            state["log_buffer"] = log_buffer
        if log_shared is not None:
            state["log_shared"] = log_shared
        return BufferConfig(
            log_buffer=state["log_buffer"], pending=0, log_shared=state["log_shared"]
        )

    register_eval("e1", 5, buffer_provider=_buffer)

    result = await eval_buffer_config("e1", log_buffer=3, log_shared=None)
    assert result == {"log_buffer": 3, "pending": 0, "log_shared": 30}
    # the unset param is left untouched
    assert state == {"log_buffer": 3, "log_shared": 30}


async def test_buffer_directive_none_when_missing() -> None:
    assert await eval_buffer_config("nope") is None
    register_eval("e1", 5)  # no buffer provider
    assert await eval_buffer_config("e1") is None


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------


def _app():
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_flush_route_ok_and_404() -> None:
    async def _flush() -> int:
        return 4

    register_eval("e1", 5, flush_provider=_flush)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post("/evals/e1/flush")
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"flushed": 4}

        missing = await client.post("/evals/missing/flush")
        assert missing.status_code == 404


async def test_buffer_route_get_and_post() -> None:
    current = BufferConfig(log_buffer=10, pending=1, log_shared=None)

    def _buffer(log_buffer: int | None, log_shared: int | None) -> BufferConfig:
        nonlocal current
        current = current._replace(
            log_buffer=log_buffer if log_buffer is not None else current.log_buffer,
            log_shared=log_shared if log_shared is not None else current.log_shared,
        )
        return current

    register_eval("e1", 5, buffer_provider=_buffer)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        got = await client.get("/evals/e1/buffer")
        assert got.status_code == 200, got.text
        assert got.json() == {"log_buffer": 10, "pending": 1, "log_shared": None}

        posted = await client.post("/evals/e1/buffer", params={"log_buffer": 2})
        assert posted.status_code == 200, posted.text
        assert posted.json()["log_buffer"] == 2
        assert current.log_buffer == 2

        missing = await client.get("/evals/missing/buffer")
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def test_print_buffer_config(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_buffer_config

    _print_buffer_config(
        {"log_buffer": 7, "pending": 3, "log_shared": 30}, changed=False
    )
    out = capsys.readouterr().out
    assert "buffer config:" in out
    assert "7 samples" in out
    assert "3 buffered" in out
    assert "30s" in out

    _print_buffer_config(
        {"log_buffer": 1, "pending": 0, "log_shared": None}, changed=True
    )
    out = capsys.readouterr().out
    assert "updated buffer config:" in out
    assert "off" in out


def test_flush_route_error_becomes_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider exception surfaces as the structured 500 (not a bare crash)."""
    from inspect_ai._control import server as server_mod

    async def _boom() -> int:
        raise RuntimeError("disk full")

    register_eval("e1", 5, flush_provider=_boom)

    async def scenario() -> httpx.Response:
        app = server_mod.ControlServer(run_id="test")._build_app()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            return await client.post("/evals/e1/flush")

    response = asyncio.run(scenario())
    assert response.status_code == 500
    assert "disk full" in response.json()["error"]
