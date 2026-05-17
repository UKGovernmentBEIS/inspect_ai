"""Tests for the non-standard ``inspect/*`` action methods.

Covers ``inspect/cancel_sample`` (terminal sample-level cancel with
score/error gate) and ``inspect/cancel_tool_call`` (per-tool cancel,
including nested tools inside ``task`` / ``as_tool`` / ``handoff``
sub-agent dispatches).

Both methods are inbound JSON-RPC requests; both validate the
connection's ``wire_session_id`` first; both look up the bound
``ActiveSample`` via ``_find_active_sample`` and operate on the
sample's primitives (``ActiveSample.interrupt`` / ``ToolEvent._cancel``).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import anyio
import pytest
from acp.exceptions import RequestError
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp import _picker
from inspect_ai.agent._acp._connection import (
    _ConnectionHandler,
    _find_active_sample,
)
from inspect_ai.agent._acp._server import acp_server
from inspect_ai.event import SpanBeginEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript
from inspect_ai.util._span import AGENT_SPAN_TYPE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _handler(
    *, wire_session_id: str = "wire", target_session_id: str | None = "tgt"
) -> _ConnectionHandler:
    """Fresh handler primed for direct method calls (no socket).

    ``target_session_id=None`` keeps the connection unbound (no
    ``binding`` assignment) so tests can exercise the
    "called before binding" rejection paths. Otherwise the handler
    is set to :class:`Bound` for the given wire+target pair.
    """
    from inspect_ai.agent._acp._connection import Bound

    h = _ConnectionHandler()
    if target_session_id is not None:
        h.state.binding = Bound(
            wire_session_id=wire_session_id, target_session_id=target_session_id
        )
    return h


def _stub_active_sample(
    *,
    target_session_id: str = "tgt",
    fails_on_error: bool = False,
    transcript: Transcript | None = None,
) -> Any:
    """Build a stub ActiveSample that ``_find_active_sample`` can return.

    Real ``ActiveSample`` needs a task group for ``interrupt()`` to
    actually fire — for unit tests we use a MagicMock so ``interrupt``
    just records the call. Integration tests that exercise real
    teardown live in test #17.
    """
    sample = MagicMock()
    sample.fails_on_error = fails_on_error
    sample.transcript = transcript or Transcript()
    sess = MagicMock()
    sess.session_id = target_session_id
    sample.acp_session = sess
    return sample


@pytest.fixture
def patch_active_samples(monkeypatch):
    """Patch ``inspect_ai.log._samples.active_samples`` to a controlled list.

    Also patches the picker's local import so the two views agree.
    """

    def _patch(*samples: Any) -> None:
        monkeypatch.setattr(
            "inspect_ai.log._samples.active_samples", lambda: list(samples)
        )
        monkeypatch.setattr(_picker, "active_samples", lambda: list(samples))

    return _patch


# ---------------------------------------------------------------------------
# Unit tests — cancel_sample handler logic
# ---------------------------------------------------------------------------


async def test_cancel_sample_rejects_mismatched_session_id(
    patch_active_samples,
) -> None:
    """invalid_params when the incoming sessionId doesn't match wire id."""
    patch_active_samples(_stub_active_sample())
    h = _handler()
    with pytest.raises(RequestError) as exc:
        await h.cancel_sample(session_id="some-other-id", action="score")
    assert exc.value.code == -32602  # invalid_params
    assert exc.value.data is not None
    assert exc.value.data["expected"] == "wire"


async def test_cancel_sample_rejects_unbound_connection(patch_active_samples) -> None:
    """invalid_request when the connection has no bound target."""
    patch_active_samples(_stub_active_sample())
    h = _handler(target_session_id=None)
    with pytest.raises(RequestError) as exc:
        await h.cancel_sample(session_id="wire", action="score")
    assert exc.value.code == -32600  # invalid_request


async def test_cancel_sample_when_sample_gone_returns_internal_error(
    patch_active_samples,
) -> None:
    """internal_error when the bound sample has finished + disappeared."""
    patch_active_samples()  # no samples
    h = _handler()
    with pytest.raises(RequestError) as exc:
        await h.cancel_sample(session_id="wire", action="score")
    assert exc.value.code == -32603  # internal_error
    assert exc.value.data is not None
    assert exc.value.data["reason"] == "bound sample no longer active"


async def test_cancel_sample_error_action_gated_by_fails_on_error(
    patch_active_samples,
) -> None:
    """action='error' rejected when sample.fails_on_error is True (TUI parity)."""
    patch_active_samples(_stub_active_sample(fails_on_error=True))
    h = _handler()
    with pytest.raises(RequestError) as exc:
        await h.cancel_sample(session_id="wire", action="error")
    assert exc.value.code == -32602
    assert exc.value.data is not None
    assert "fails_on_error=True" in exc.value.data["reason"]


async def test_cancel_sample_score_action_calls_interrupt(
    patch_active_samples,
) -> None:
    """action='score' calls sample.interrupt('score')."""
    sample = _stub_active_sample()
    patch_active_samples(sample)
    h = _handler()
    result = await h.cancel_sample(session_id="wire", action="score")
    assert result == {}
    sample.interrupt.assert_called_once_with("score")


async def test_cancel_sample_error_action_allowed_when_gate_passes(
    patch_active_samples,
) -> None:
    """action='error' is accepted when fails_on_error=False; calls interrupt."""
    sample = _stub_active_sample(fails_on_error=False)
    patch_active_samples(sample)
    h = _handler()
    result = await h.cancel_sample(session_id="wire", action="error")
    assert result == {}
    sample.interrupt.assert_called_once_with("error")


# ---------------------------------------------------------------------------
# Unit tests — cancel_tool_call handler logic
# ---------------------------------------------------------------------------


def _pending_tool_event(
    *,
    tool_id: str = "tc1",
    function: str = "bash",
    cancel_fn: Any = None,
) -> ToolEvent:
    """Build a pending ToolEvent with an optional cancel function."""
    event = ToolEvent(
        id=tool_id,
        function=function,
        arguments={},
        pending=True,
    )
    if cancel_fn is not None:
        event._set_cancel_fn(cancel_fn)
    return event


async def test_cancel_tool_call_rejects_mismatched_session_id(
    patch_active_samples,
) -> None:
    patch_active_samples(_stub_active_sample())
    h = _handler()
    with pytest.raises(RequestError) as exc:
        await h.cancel_tool_call(session_id="some-other-id", tool_call_id="tc1")
    assert exc.value.code == -32602


async def test_cancel_tool_call_rejects_unbound_connection(
    patch_active_samples,
) -> None:
    patch_active_samples(_stub_active_sample())
    h = _handler(target_session_id=None)
    with pytest.raises(RequestError) as exc:
        await h.cancel_tool_call(session_id="wire", tool_call_id="tc1")
    assert exc.value.code == -32600


async def test_cancel_tool_call_unknown_id_returns_cancelled_false(
    patch_active_samples,
) -> None:
    """Idempotent: unknown id returns {cancelled: false}, NOT an error."""
    tr = Transcript()
    tr._event(_pending_tool_event(tool_id="other-id"))
    patch_active_samples(_stub_active_sample(transcript=tr))
    h = _handler()
    result = await h.cancel_tool_call(session_id="wire", tool_call_id="not-found")
    assert result == {"cancelled": False}


async def test_cancel_tool_call_already_completed_returns_cancelled_false(
    patch_active_samples,
) -> None:
    """A non-pending ToolEvent isn't cancellable; idempotent miss."""
    tr = Transcript()
    event = ToolEvent(id="tc-done", function="bash", arguments={}, pending=None)
    tr._event(event)
    patch_active_samples(_stub_active_sample(transcript=tr))
    h = _handler()
    result = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-done")
    assert result == {"cancelled": False}


async def test_cancel_tool_call_pending_tool_invokes_cancel_fn(
    patch_active_samples,
) -> None:
    """A pending ToolEvent with _cancel_fn is cancelled; returns true."""
    cancel_calls: list[None] = []
    tr = Transcript()
    tr._event(
        _pending_tool_event(
            tool_id="tc-live", cancel_fn=lambda: cancel_calls.append(None)
        )
    )
    patch_active_samples(_stub_active_sample(transcript=tr))
    h = _handler()
    result = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-live")
    assert result == {"cancelled": True}
    assert len(cancel_calls) == 1


async def test_cancel_tool_call_pending_without_cancel_fn_returns_false(
    patch_active_samples,
) -> None:
    """A pending ToolEvent that has no ``_cancel_fn`` set cannot be cancelled.

    ``ToolEvent._cancel()`` no-ops when ``_cancel_fn is None``
    (``src/inspect_ai/event/_tool.py:123``). The handler must read
    the post-call ``event.cancelled`` state and report ``False`` so
    the client doesn't disable its cancel UI based on a false
    success. In current production paths ``_call_tools.py:348``
    always installs the cancel_fn before the event reaches the
    transcript, but this guards against future paths and against
    a misleading return value if that invariant ever changes.
    """
    tr = Transcript()
    tr._event(_pending_tool_event(tool_id="tc-no-fn", cancel_fn=None))
    patch_active_samples(_stub_active_sample(transcript=tr))
    h = _handler()
    result = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-no-fn")
    assert result == {"cancelled": False}


async def test_cancel_tool_call_repeat_on_cancelled_tool_is_idempotent_true(
    patch_active_samples,
) -> None:
    """Repeat cancel on an already-cancelled-but-still-pending tool returns True.

    Once ``_cancel()`` has flipped ``_cancelled``, a second
    ``_cancel()`` no-ops (the ``not self.cancelled`` guard). The
    handler still reports ``True`` because the tool IS cancelled —
    the client's question ("is this tool cancelled?") is answered
    accurately. Cancel_fn must fire exactly once.
    """
    cancel_calls: list[None] = []
    tr = Transcript()
    tr._event(
        _pending_tool_event(
            tool_id="tc-twice", cancel_fn=lambda: cancel_calls.append(None)
        )
    )
    patch_active_samples(_stub_active_sample(transcript=tr))
    h = _handler()
    first = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-twice")
    second = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-twice")
    assert first == {"cancelled": True}
    assert second == {"cancelled": True}
    # cancel_fn fired exactly once — the second _cancel() is the no-op branch.
    assert len(cancel_calls) == 1


async def test_cancel_tool_call_finds_nested_tool(patch_active_samples) -> None:
    """Walks the FULL transcript: nested ToolEvents inside an agent span are found.

    The TUI's button only looks at top-level tools (via events[-1]
    heuristic); the JSON-RPC method has no such restriction. A tool
    inside a ``task`` / ``as_tool`` / ``handoff`` sub-agent dispatch
    must be reachable by id.
    """
    cancel_calls: list[None] = []
    tr = Transcript()
    # Outer top-level tool (which would have dispatched the sub-agent).
    tr._event(_pending_tool_event(tool_id="tc-outer", function="task"))
    # Simulate the AGENT_SPAN_TYPE span the sub-agent dispatch opens.
    tr._event(SpanBeginEvent(id="span-1", name="subagent", type=AGENT_SPAN_TYPE))
    # Nested tool inside the sub-agent.
    tr._event(
        _pending_tool_event(
            tool_id="tc-nested",
            function="bash",
            cancel_fn=lambda: cancel_calls.append(None),
        )
    )
    patch_active_samples(_stub_active_sample(transcript=tr))
    h = _handler()
    result = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-nested")
    assert result == {"cancelled": True}
    assert len(cancel_calls) == 1


async def test_cancel_tool_call_when_sample_gone_returns_cancelled_false(
    patch_active_samples,
) -> None:
    """Idempotent: missing sample returns {cancelled: false}, NOT an error."""
    patch_active_samples()  # no samples
    h = _handler()
    result = await h.cancel_tool_call(session_id="wire", tool_call_id="anything")
    assert result == {"cancelled": False}


# ---------------------------------------------------------------------------
# Unit test — _find_active_sample helper
# ---------------------------------------------------------------------------


def test_find_active_sample_returns_matching_sample(monkeypatch) -> None:
    """Walks active_samples for the matching acp_session.session_id."""
    sample_a = _stub_active_sample(target_session_id="sess-a")
    sample_b = _stub_active_sample(target_session_id="sess-b")
    monkeypatch.setattr(
        "inspect_ai.log._samples.active_samples",
        lambda: [sample_a, sample_b],
    )
    assert _find_active_sample("sess-a") is sample_a
    assert _find_active_sample("sess-b") is sample_b
    assert _find_active_sample("nope") is None


# ---------------------------------------------------------------------------
# Integration tests over a real socket
# ---------------------------------------------------------------------------


@pytest.fixture
def short_data_dir(monkeypatch):
    """Short /tmp data dir so AF_UNIX paths fit in 104 chars on macOS."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_act_", dir="/tmp"))

    def _stub_data_dir(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "inspect_ai.agent._acp._discovery.inspect_data_dir",
        _stub_data_dir,
    )
    try:
        yield dirpath
    finally:
        for p in dirpath.rglob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            for sub in sorted(dirpath.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            dirpath.rmdir()
        except OSError:
            pass


class _RpcClient:
    """Line-oriented JSON-RPC 2.0 client (copy of the test pattern)."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    return
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                elif "method" in msg:
                    await self._notifications.put(msg)
        except (asyncio.CancelledError, ConnectionError):
            return

    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        self._writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._writer.drain()
        return await asyncio.wait_for(fut, timeout=5.0)

    async def next_notification(self, timeout: float = 5.0) -> dict[str, Any]:
        return await asyncio.wait_for(self._notifications.get(), timeout=timeout)

    async def close(self) -> None:
        self._read_task.cancel()
        try:
            await self._read_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass


unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


async def _connect(server: Any) -> _RpcClient:
    reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
    return _RpcClient(reader, writer)


async def _initialize_and_bind(client: _RpcClient, target_session_id: str) -> str:
    """Helper: initialize, bind via session/load to a known target.

    Returns the wire_session_id (== target_session_id for direct
    loadSession). Drains the bind-confirmation notification.
    """
    await client.request(
        "initialize",
        {"protocolVersion": 1, "clientInfo": {"name": "test", "version": "0.0"}},
    )
    resp = await client.request(
        "session/load",
        {
            "cwd": "/tmp",
            "mcpServers": [],
            "sessionId": target_session_id,
        },
    )
    assert "result" in resp, resp
    await client.next_notification()  # drain confirmation
    return target_session_id


def _register_via_picker_and_samples(monkeypatch, samples: list[Any]) -> None:
    """Patch both the picker's import AND the samples module function."""
    monkeypatch.setattr(_picker, "active_samples", lambda: list(samples))
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: list(samples))


@skip_if_trio
@unix_only
async def test_cancel_sample_over_wire_score(short_data_dir: Path, monkeypatch) -> None:
    """End-to-end: client sends inspect/cancel_sample → sample.interrupt('score')."""
    sample = _stub_active_sample(target_session_id="tgt-1", fails_on_error=False)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-cs-score", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            wire = await _initialize_and_bind(client, "tgt-1")
            resp = await client.request(
                "inspect/cancel_sample",
                {"sessionId": wire, "action": "score"},
            )
            assert "result" in resp, resp
            assert resp["result"] == {}
            sample.interrupt.assert_called_once_with("score")
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_sample_over_wire_error_passes_gate(
    short_data_dir: Path, monkeypatch
) -> None:
    """End-to-end: action='error' accepted when fails_on_error=False."""
    sample = _stub_active_sample(target_session_id="tgt-2", fails_on_error=False)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-cs-err-ok", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            wire = await _initialize_and_bind(client, "tgt-2")
            resp = await client.request(
                "inspect/cancel_sample",
                {"sessionId": wire, "action": "error"},
            )
            assert "result" in resp, resp
            sample.interrupt.assert_called_once_with("error")
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_sample_over_wire_error_rejected_by_gate(
    short_data_dir: Path, monkeypatch
) -> None:
    """End-to-end: action='error' rejected with -32602 when fails_on_error=True."""
    sample = _stub_active_sample(target_session_id="tgt-3", fails_on_error=True)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-cs-err-gate", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            wire = await _initialize_and_bind(client, "tgt-3")
            resp = await client.request(
                "inspect/cancel_sample",
                {"sessionId": wire, "action": "error"},
            )
            assert "error" in resp, resp
            assert resp["error"]["code"] == -32602
            assert "fails_on_error" in resp["error"]["data"]["reason"]
            # Interrupt was NOT called.
            sample.interrupt.assert_not_called()
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_tool_call_over_wire(short_data_dir: Path, monkeypatch) -> None:
    """End-to-end: client cancels a top-level pending tool via JSON-RPC."""
    cancel_calls: list[None] = []
    tr = Transcript()
    tr._event(
        _pending_tool_event(
            tool_id="tc-wire-1",
            cancel_fn=lambda: cancel_calls.append(None),
        )
    )
    sample = _stub_active_sample(target_session_id="tgt-4", transcript=tr)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-ct-wire", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            wire = await _initialize_and_bind(client, "tgt-4")
            resp = await client.request(
                "inspect/cancel_tool_call",
                {"sessionId": wire, "toolCallId": "tc-wire-1"},
            )
            assert resp["result"] == {"cancelled": True}
            assert len(cancel_calls) == 1
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_tool_call_over_wire_nested(
    short_data_dir: Path, monkeypatch
) -> None:
    """End-to-end: client cancels a NESTED tool (inside an agent span)."""
    cancel_calls: list[None] = []
    tr = Transcript()
    tr._event(_pending_tool_event(tool_id="tc-outer", function="task"))
    tr._event(SpanBeginEvent(id="span-x", name="subagent", type=AGENT_SPAN_TYPE))
    tr._event(
        _pending_tool_event(
            tool_id="tc-inner",
            function="bash",
            cancel_fn=lambda: cancel_calls.append(None),
        )
    )
    sample = _stub_active_sample(target_session_id="tgt-5", transcript=tr)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-ct-nested", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            wire = await _initialize_and_bind(client, "tgt-5")
            resp = await client.request(
                "inspect/cancel_tool_call",
                {"sessionId": wire, "toolCallId": "tc-inner"},
            )
            assert resp["result"] == {"cancelled": True}
            assert len(cancel_calls) == 1
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_tool_call_over_wire_unknown_id(
    short_data_dir: Path, monkeypatch
) -> None:
    """End-to-end: unknown tool id returns {cancelled: false}, not an error."""
    sample = _stub_active_sample(target_session_id="tgt-6", transcript=Transcript())
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-ct-miss", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            wire = await _initialize_and_bind(client, "tgt-6")
            resp = await client.request(
                "inspect/cancel_tool_call",
                {"sessionId": wire, "toolCallId": "does-not-exist"},
            )
            assert resp["result"] == {"cancelled": False}
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Audit: methods are always advertised (no capability opt-in)
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_cancel_sample_is_always_advertised(
    short_data_dir: Path, monkeypatch
) -> None:
    """Method is registered on every connection without capability opt-in.

    Verifies the client doesn't have to declare any ``_meta`` flag at
    initialize to reach these methods — they're always available
    (their handlers do their own validation per the standard pattern).
    """
    sample = _stub_active_sample(target_session_id="tgt-7", fails_on_error=False)
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-audit-1", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            # Initialize with NO `clientCapabilities._meta`.
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "no-meta", "version": "0"},
                },
            )
            await client.request(
                "session/load",
                {"cwd": "/tmp", "mcpServers": [], "sessionId": "tgt-7"},
            )
            await client.next_notification()  # drain
            resp = await client.request(
                "inspect/cancel_sample",
                {"sessionId": "tgt-7", "action": "score"},
            )
            # Dispatch succeeded — NOT method_not_found.
            assert "result" in resp, resp
            assert resp["error"]["code"] != -32601 if "error" in resp else True
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_tool_call_is_always_advertised(
    short_data_dir: Path, monkeypatch
) -> None:
    """Same for inspect/cancel_tool_call — no capability opt-in needed."""
    sample = _stub_active_sample(target_session_id="tgt-8", transcript=Transcript())
    _register_via_picker_and_samples(monkeypatch, [sample])

    async with acp_server(eval_id="evt-audit-2", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "no-meta", "version": "0"},
                },
            )
            await client.request(
                "session/load",
                {"cwd": "/tmp", "mcpServers": [], "sessionId": "tgt-8"},
            )
            await client.next_notification()  # drain
            resp = await client.request(
                "inspect/cancel_tool_call",
                {"sessionId": "tgt-8", "toolCallId": "irrelevant"},
            )
            assert "result" in resp, resp
            # Idempotent miss is the expected response (no tool with that id).
            assert resp["result"] == {"cancelled": False}
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Cancel propagation — pins the contract that
# ``inspect/cancel_tool_call`` → ``ToolEvent._cancel`` → the tool's task
# group cancel_scope.  Future changes to ``_call_tools.py``'s
# task-group structure or to ``Transcript.events`` walking can't
# silently break the chain — they'll fail this test.
# ---------------------------------------------------------------------------


async def test_cancel_tool_call_propagates_through_nested_dispatch(
    patch_active_samples,
) -> None:
    """End-to-end propagation: cancel_tool_call → ToolEvent._cancel → task-group cancel.

    Mirrors the cancel wiring that ``_call_tools.py`` installs for
    every running tool call (``event._set_cancel_fn(tg.cancel_scope.cancel)``
    at line 348). The slow body lives in a real anyio task group; its
    ToolEvent sits *inside* an ``AGENT_SPAN_TYPE`` span in the transcript
    (the same span that ``task`` / ``as_tool`` / ``handoff`` dispatch
    opens). When the cancel fires:

    1. The handler walks the **full** transcript (not just top-level
       events) to find the pending nested ``ToolEvent``.
    2. ``event._cancel()`` invokes the bound cancel_fn, which cancels
       the tool's own task-group scope.
    3. The slow body's ``await`` raises ``CancelledError``; the task
       group exits without hanging.
    4. ``event.cancelled`` becomes ``True`` so downstream renderers /
       the ACP event stream see the row as cancelled.

    What this *does not* assert (and shouldn't): that the **outer**
    ``task`` tool call also fails. Per ``_call_tools.py:346-348``,
    each tool call has its OWN task group; cancelling one doesn't
    cancel a sibling. The sub-agent's react loop sees a synthesized
    ``ChatMessageTool`` with ``error.type == "timeout"`` and decides
    what to do next (typically: continue with a different tool call
    or submit). The outer ``task`` tool returns whatever the sub-agent
    eventually produces. If a future refactor changes the per-call
    scope to a per-turn scope, this test should be revisited.
    """
    transcript = Transcript()

    # Outer top-level tool that "dispatched" the sub-agent (analogous
    # to the deepagent ``task`` tool). Not the target of cancel —
    # included so the walk has to traverse past it.
    transcript._event(_pending_tool_event(tool_id="tc-outer", function="task"))

    # The agent-span boundary that ``task`` / ``as_tool`` / ``handoff``
    # opens around the sub-agent's body.
    transcript._event(
        SpanBeginEvent(id="span-sub", name="custom_sub", type=AGENT_SPAN_TYPE)
    )

    # Set up the cancel-propagation harness in a real task group.
    body_started = anyio.Event()
    body_cancelled: list[str] = []

    async def slow_body() -> None:
        body_started.set()
        try:
            # Long enough that the cancel must fire to release us; if
            # the cancel chain is broken this becomes a timeout.
            await anyio.sleep(30)
        except BaseException as exc:  # noqa: BLE001 — we want the cancel class
            if isinstance(exc, anyio.get_cancelled_exc_class()):
                body_cancelled.append("cancelled")
            raise

    async with anyio.create_task_group() as tg:
        # Create the pending nested ToolEvent — same construction the
        # sub-agent's _call_tools loop would do.
        nested_event = _pending_tool_event(tool_id="tc-inner", function="slow_tool")
        transcript._event(nested_event)

        # Mirror _call_tools.py:347-348 exactly:
        tg.start_soon(slow_body)
        nested_event._set_cancel_fn(tg.cancel_scope.cancel)

        # Let the slow body get into its sleep before we fire cancel.
        with anyio.fail_after(2.0):
            await body_started.wait()

        # Now drive the public handler — same path a real client takes.
        sample = _stub_active_sample(transcript=transcript)
        patch_active_samples(sample)
        h = _handler()
        result = await h.cancel_tool_call(session_id="wire", tool_call_id="tc-inner")

    # Task group has exited — verify the propagation chain end-to-end:

    # 1. Handler reported the cancel landed.
    assert result == {"cancelled": True}

    # 2. Slow body's await actually raised CancelledError (the
    # task-group scope cancel reached it).
    assert body_cancelled == ["cancelled"], (
        "slow body did not observe a CancelledError — the chain "
        "ToolEvent._cancel → cancel_fn → tg.cancel_scope.cancel is "
        "broken or no longer reaches the awaiting body"
    )

    # 3. ToolEvent.cancelled is set so the eval log / live event
    # stream can render the row as cancelled.
    assert nested_event.cancelled is True

    # 4. The OUTER tool wasn't touched (per-call scope, not per-turn).
    outer_events = [
        e for e in transcript.events if isinstance(e, ToolEvent) and e.id == "tc-outer"
    ]
    assert len(outer_events) == 1
    assert outer_events[0].cancelled is False, (
        "outer task tool was unexpectedly cancelled — per-call scope "
        "in _call_tools.py:346 may have changed to a wider scope; "
        "revisit the propagation contract documented at the top of "
        "this test"
    )
