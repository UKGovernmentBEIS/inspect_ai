"""In-process tests for ``bridge_stdio()``.

Each test spins up a real ``acp_server`` over an AF_UNIX socket and
drives the bridge with in-memory ``StreamReader`` / ``StreamWriter``
pairs that stand in for the editor's stdin/stdout. This avoids
spawning a subprocess (which would make the tests slow + flaky) while
still exercising the real socket-layer round-trip + EOF semantics
that production traffic depends on.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp import picker
from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.stdio import bridge_stdio
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript

unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


@pytest.fixture
def short_data_dir(monkeypatch):
    """Short /tmp data dir so AF_UNIX paths fit in 104 chars on macOS."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_bridge_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "inspect_ai.agent._acp.discovery.inspect_data_dir",
        _stub,
    )
    try:
        yield dirpath
    finally:
        for p in sorted(dirpath.rglob("*"), reverse=True):
            try:
                if p.is_dir():
                    p.rmdir()
                else:
                    p.unlink()
            except OSError:
                pass
        try:
            dirpath.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# In-memory stream pair for driving the bridge from a test
# ---------------------------------------------------------------------------


class _CapturingTransport(asyncio.WriteTransport):
    """Asyncio transport that appends every ``write()`` to a buffer.

    Allows tests to construct an :class:`asyncio.StreamWriter` that
    captures bytes in memory instead of sending them to a real socket.
    """

    def __init__(self, buf: bytearray, on_write: asyncio.Event) -> None:
        super().__init__()
        self._buf = buf
        self._on_write = on_write
        self._closed = False

    def write(self, data: Any) -> None:
        if self._closed:
            return
        self._buf.extend(data)
        self._on_write.set()

    def close(self) -> None:
        self._closed = True

    def is_closing(self) -> bool:
        return self._closed

    def can_write_eof(self) -> bool:
        return False

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return default


class _NoopProtocol(asyncio.BaseProtocol):
    """StreamWriter requires a protocol with a ``_drain_helper`` coro."""

    async def _drain_helper(self) -> None:  # noqa: ARG002 — required signature
        return None


class _MockStdio:
    """Bidirectional in-memory stand-in for editor stdin/stdout.

    The bridge reads from :attr:`stdin_reader` (test calls
    :meth:`stdin_send_frame` to push JSON-RPC requests through);
    writes to :attr:`stdout_writer` (test calls
    :meth:`stdout_read_frame` to pull JSON-RPC responses out).
    """

    def __init__(self) -> None:
        loop = asyncio.get_event_loop()
        self.stdin_reader = asyncio.StreamReader(loop=loop)
        self._stdout_buf = bytearray()
        self._stdout_event = asyncio.Event()
        self.stdout_writer = asyncio.StreamWriter(
            _CapturingTransport(self._stdout_buf, self._stdout_event),
            _NoopProtocol(),
            None,
            loop,
        )

    # -- stdin helpers --------------------------------------------------

    def stdin_send_frame(self, payload: dict[str, Any]) -> None:
        """Push one JSON-RPC frame into the bridge as if from the editor."""
        line = (json.dumps(payload) + "\n").encode("utf-8")
        self.stdin_reader.feed_data(line)

    def stdin_send_raw(self, data: bytes) -> None:
        """Push raw bytes (for framing-integrity tests)."""
        self.stdin_reader.feed_data(data)

    def stdin_close(self) -> None:
        self.stdin_reader.feed_eof()

    # -- stdout helpers -------------------------------------------------

    async def stdout_read_frame(self, timeout: float = 2.0) -> dict[str, Any]:
        """Wait for one complete newline-delimited JSON frame on stdout."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            idx = self._stdout_buf.find(b"\n")
            if idx != -1:
                line = bytes(self._stdout_buf[: idx + 1])
                del self._stdout_buf[: idx + 1]
                return json.loads(line)
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError("stdout_read_frame timed out")
            self._stdout_event.clear()
            try:
                await asyncio.wait_for(self._stdout_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                raise TimeoutError("stdout_read_frame timed out") from None

    async def stdout_read_response(
        self, request_id: int, timeout: float = 2.0
    ) -> dict[str, Any]:
        """Read frames, skipping notifications, until one matches ``request_id``.

        ACP servers can emit notifications (e.g. picker confirmation)
        before, after, or interleaved with request responses. Tests
        that want a specific response should use this helper rather
        than ``stdout_read_frame`` directly.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = max(0.0, deadline - asyncio.get_event_loop().time())
            frame = await self.stdout_read_frame(timeout=remaining)
            if frame.get("id") == request_id:
                return frame
            # else: notification or response for some other id — drop.


def _stub_active_sample(
    *,
    target_session_id: str,
    transcript: Transcript | None = None,
    fails_on_error: bool = False,
) -> Any:
    sample = MagicMock()
    sample.fails_on_error = fails_on_error
    sample.transcript = transcript or Transcript()
    sess = MagicMock()
    sess.session_id = target_session_id
    sample.acp_session = sess
    return sample


def _register_via_picker_and_samples(monkeypatch, samples: list[Any]) -> None:
    monkeypatch.setattr(picker, "active_samples", lambda: list(samples))
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: list(samples))


async def _drive_bridge_until_eof(
    io: _MockStdio,
    target: TargetAddress,
) -> asyncio.Task[None]:
    """Start ``bridge_stdio`` as a background task; return the handle.

    Tests are responsible for closing ``io.stdin`` (or the server) so
    the bridge eventually exits and the task completes.
    """
    task = asyncio.create_task(bridge_stdio(io.stdin_reader, io.stdout_writer, target))
    # Give the bridge a moment to open the socket before tests start
    # pumping data through. Without this the first stdin_send_frame
    # can race the socket open and feed the connection before it
    # exists. (StreamReader buffers fine; this is paranoia.)
    await asyncio.sleep(0)
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_initialize_round_trip(short_data_dir: Path) -> None:
    """Initialize request → server → response back through bridge."""
    async with acp_server(eval_id="bridge-init", transport=True) as server:
        assert server is not None and server.socket_path is not None
        target = TargetAddress(socket_path=server.socket_path)
        io = _MockStdio()
        task = await _drive_bridge_until_eof(io, target)
        try:
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
            resp = await io.stdout_read_response(1)
            assert "result" in resp, resp
            assert resp["result"]["protocolVersion"] >= 1
        finally:
            io.stdin_close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=2.0)


@skip_if_trio
@unix_only
async def test_session_load_round_trip(short_data_dir: Path, monkeypatch) -> None:
    """Initialize → session/load → bind confirmation, all through the bridge."""
    sample = _stub_active_sample(target_session_id="bridge-sess-1")
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="bridge-load", transport=True) as server:
        assert server is not None and server.socket_path is not None
        target = TargetAddress(socket_path=server.socket_path)
        io = _MockStdio()
        task = await _drive_bridge_until_eof(io, target)
        try:
            # initialize first (server requires it before session ops)
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
            init_resp = await io.stdout_read_response(1)
            assert "result" in init_resp
            # session/load
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/load",
                    "params": {
                        "cwd": "/tmp",
                        "mcpServers": [],
                        "sessionId": "bridge-sess-1",
                    },
                }
            )
            load_resp = await io.stdout_read_response(2)
            assert "result" in load_resp, load_resp
        finally:
            io.stdin_close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=2.0)


@skip_if_trio
@unix_only
async def test_inspect_cancel_tool_call_round_trip(
    short_data_dir: Path, monkeypatch
) -> None:
    """Custom inspect/cancel_tool_call request flows through the bridge."""
    cancel_calls: list[None] = []
    tr = Transcript()
    event = ToolEvent(id="tc-bridge", function="bash", arguments={}, pending=True)
    event._set_cancel_fn(lambda: cancel_calls.append(None))
    tr._event(event)
    sample = _stub_active_sample(target_session_id="bridge-sess-2", transcript=tr)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="bridge-cancel", transport=True) as server:
        assert server is not None and server.socket_path is not None
        target = TargetAddress(socket_path=server.socket_path)
        io = _MockStdio()
        task = await _drive_bridge_until_eof(io, target)
        try:
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
            await io.stdout_read_response(1)
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/load",
                    "params": {
                        "cwd": "/tmp",
                        "mcpServers": [],
                        "sessionId": "bridge-sess-2",
                    },
                }
            )
            await io.stdout_read_response(2)
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "inspect/cancel_tool_call",
                    "params": {
                        "sessionId": "bridge-sess-2",
                        "toolCallId": "tc-bridge",
                    },
                }
            )
            cancel_resp = await io.stdout_read_response(3)
            assert cancel_resp["result"] == {"cancelled": True}
            assert len(cancel_calls) == 1
        finally:
            io.stdin_close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=2.0)


@skip_if_trio
@unix_only
async def test_eof_on_stdin_exits_bridge_cleanly(short_data_dir: Path) -> None:
    """Closing the mock stdin propagates to the socket and ends the bridge."""
    async with acp_server(eval_id="bridge-eof-stdin", transport=True) as server:
        assert server is not None and server.socket_path is not None
        target = TargetAddress(socket_path=server.socket_path)
        io = _MockStdio()
        task = await _drive_bridge_until_eof(io, target)
        # Send no frames; immediately close stdin.
        io.stdin_close()
        # Bridge should exit promptly (one EOF → close socket writer →
        # server closes its end → bridge's reader side exits → bridge
        # returns).
        await asyncio.wait_for(task, timeout=2.0)
        assert task.done()
        assert task.exception() is None


@skip_if_trio
@unix_only
async def test_eof_on_socket_exits_bridge_cleanly(short_data_dir: Path) -> None:
    """Server closing its end of the socket tears down the bridge.

    Simulates an editor → eval crash scenario: we tear down only the
    eval's connection-side writer (the same effect ``server.stop()``
    eventually has on each live connection via its cancel-cascade).
    The bridge's socket-reader sees EOF; with the FIRST_COMPLETED
    forwarder design, the bridge cancels its sibling stdin-reader and
    returns. We DON'T call ``server.stop()`` here because that path
    blocks on the connection's main_loop draining, which itself is
    blocked on the bridge's stdin (still open in this scenario) —
    that interaction is a deadlock on `inspect_ai`'s shutdown side,
    not the bridge's responsibility.
    """
    async with acp_server(eval_id="bridge-eof-sock", transport=True) as server:
        assert server is not None and server.socket_path is not None
        target = TargetAddress(socket_path=server.socket_path)
        io = _MockStdio()
        task = await _drive_bridge_until_eof(io, target)
        try:
            # Drive one round-trip so a server-side connection exists
            # in ``server._connections`` for us to close.
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                }
            )
            await io.stdout_read_response(1)
            # Close the server's writer for this connection directly.
            # That sends EOF to the bridge's socket reader without
            # touching the server's main_loop (which would deadlock
            # on our still-open stdin).
            for conn in list(server._connections):
                writer = getattr(conn, "_writer", None) or getattr(conn, "writer", None)
                if writer is not None:
                    with contextlib.suppress(Exception):
                        writer.close()
            await asyncio.wait_for(task, timeout=2.0)
            assert task.done()
            assert task.exception() is None
        finally:
            # Close stdin to satisfy the bridge's cleanup; harmless if
            # the bridge has already exited.
            io.stdin_close()


@skip_if_trio
@unix_only
async def test_framing_integrity_multiline_content(
    short_data_dir: Path, monkeypatch
) -> None:
    r"""Embedded ``\n`` characters in JSON string values round-trip as one frame.

    Pins the line-framed forwarder against accidental refactors that
    might switch to a byte-chunked copy and lose the "exactly one
    frame per newline" invariant.
    """
    sample = _stub_active_sample(target_session_id="bridge-sess-3")
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="bridge-frame", transport=True) as server:
        assert server is not None and server.socket_path is not None
        target = TargetAddress(socket_path=server.socket_path)
        io = _MockStdio()
        task = await _drive_bridge_until_eof(io, target)
        try:
            io.stdin_send_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {
                            "name": "test\nwith\nembedded\nnewlines",
                            "version": "0",
                        },
                    },
                }
            )
            resp = await io.stdout_read_response(1)
            # The fact that we got a *single* parseable frame back
            # (instead of a JSONDecodeError) is the framing-integrity
            # guarantee. The `\n` in the string value was preserved as
            # an escaped ``\\n`` per JSON encoding, not a literal
            # newline that would have split the frame.
            assert "result" in resp
        finally:
            io.stdin_close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=2.0)
