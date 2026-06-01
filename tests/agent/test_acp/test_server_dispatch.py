"""Phase 9 integration tests for the picker / dispatch layer of `AcpServer`.

These tests exercise the full request/response + notification cycle
over a real AF_UNIX loopback socket. They stub `picker.active_samples`
to control the target list rather than spinning up real eval samples.

Notification ordering rule we rely on: the ACP server pushes
`session/update` notifications by calling `connection.send_notification`
*after* the request handler returns its response. For `session/new` /
`session/load` that means the response arrives first, then any
picker / confirmation notification. The `_RpcClient` helper queues
incoming notifications so tests can drain them in arrival order.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp import picker
from inspect_ai.agent._acp.connection import (
    Bound,
    ConnectionHandler,
)
from inspect_ai.agent._acp.inspect_ext import PICKER_META_KEY
from inspect_ai.agent._acp.picker import PickerTarget
from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.session_router import Forwarders

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def short_data_dir(monkeypatch):
    """A short data directory under /tmp so AF_UNIX paths fit in 104 chars."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_disp_", dir="/tmp"))

    def _stub_data_dir(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(
        "inspect_ai.agent._acp.discovery.inspect_data_dir",
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


def _make_sample(
    *,
    task: str,
    sample_id: str | int,
    epoch: int,
    session_id: str | None,
    agent_name: str | None = None,
    started: float | None = None,
    total_messages: int = 0,
    total_tokens: int = 0,
    fails_on_error: bool = True,
) -> Any:
    sample = MagicMock()
    sample.id = sample_id
    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    # Explicit values on the fields read by ``list_picker_targets`` so
    # MagicMock doesn't auto-wrap them and break JSON serialization
    # downstream. ``total_messages`` / ``total_tokens`` / ``fails_on_error``
    # are serialised over the wire by both the picker meta and
    # ``inspect/list_sessions`` — must be real Python values, not
    # MagicMocks, or the server crashes silently in a background task
    # and the request hangs forever. Default ``fails_on_error=True``
    # mirrors what the eval harness produces from the default
    # ``EvalConfig.fail_on_error=None`` (None collapses to True in
    # ``ActiveSample.fails_on_error``).
    active.agent_name = agent_name
    active.started = started
    active.total_messages = total_messages
    active.total_tokens = total_tokens
    active.fails_on_error = fails_on_error
    # ``pending_interaction`` is read by ``list_all_samples`` into the
    # serialized ``inspect/list_samples`` payload — must be a real
    # ``None`` / ``"approval"`` / ``"question"``, not a MagicMock.
    # Same hazard as the fields above.
    active.pending_interaction = None
    if session_id is None:
        active.acp_transport = None
    else:
        session = MagicMock()
        session.session_id = session_id
        # Match production semantics: noop placeholder is neither
        # interactive nor attachable, real bound sessions are both.
        # Without this the MagicMock's auto-generated attributes are
        # truthy, and the picker's ``is_interactive`` filter wouldn't
        # strip the noop sentinel.
        session.is_interactive = session_id != "noop"
        session.is_attachable = session_id != "noop"
        active.acp_transport = session
    return active


@pytest.fixture
def stub_targets(monkeypatch):
    """Helper that patches `picker.active_samples` to a controlled list."""

    def _set(samples: list[Any]) -> None:
        monkeypatch.setattr(picker, "active_samples", lambda: samples)

    return _set


# ---------------------------------------------------------------------------
# Minimal JSON-RPC client (test-only)
# ---------------------------------------------------------------------------


class _RpcClient:
    """Tiny line-oriented JSON-RPC 2.0 client.

    Sends requests and awaits the response with the matching id;
    queues incoming notifications for tests to drain via
    `next_notification`. Runs a background reader task while open.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Append-only record of every frame in the order it was read off
        # the wire. Entries are ``("response", id)`` or
        # ``("notification", method)``. Tests that need to assert wire
        # ordering between responses and notifications read this.
        self.arrival_log: list[tuple[str, Any]] = []
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
                    self.arrival_log.append(("response", msg["id"]))
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                elif "method" in msg:
                    self.arrival_log.append(("notification", msg["method"]))
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

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._writer.drain()

    async def next_notification(self, timeout: float = 5.0) -> dict[str, Any]:
        return await asyncio.wait_for(self._notifications.get(), timeout=timeout)

    def notification_pending(self) -> bool:
        return not self._notifications.empty()

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


# Pytest skip decorators reused across tests.
unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


async def _connect(server: Any) -> _RpcClient:
    reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
    return _RpcClient(reader, writer)


# ---------------------------------------------------------------------------
# initialize handshake
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_initialize_returns_capabilities(short_data_dir: Path) -> None:
    """`initialize` returns a well-formed InitializeResponse."""
    async with acp_server(eval_id="evt-init", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "initialize",
                {"protocolVersion": 1, "clientCapabilities": {}},
            )
            assert "result" in resp
            result = resp["result"]
            assert result["protocolVersion"] == 1
            assert "agentCapabilities" in result
            assert result["agentInfo"]["name"] == "inspect-ai"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# session/new — picker / auto-bind / no-targets
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_session_new_with_multiple_targets_returns_control_session(
    short_data_dir: Path, stub_targets
) -> None:
    """Two targets → response carries a control sessionId; picker is pushed."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=1, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-new-2", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            assert "result" in resp
            control_id = resp["result"]["sessionId"]
            # Control sessionId is NOT one of the target uuids.
            assert control_id not in ("uuid-a", "uuid-b")

            notif = await client.next_notification()
            assert notif["method"] == "session/update"
            params = notif["params"]
            assert params["sessionId"] == control_id
            assert params["update"]["sessionUpdate"] == "agent_message_chunk"
            text = params["update"]["content"]["text"]
            assert "1." in text and "2." in text
            assert "uuid-a" in text and "uuid-b" in text
            # _meta payload carries the structured target list.
            assert PICKER_META_KEY in params["_meta"]
            ids = [t["sessionId"] for t in params["_meta"][PICKER_META_KEY]]
            assert ids == ["uuid-a", "uuid-b"]
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_new_picker_notification_arrives_after_response(
    short_data_dir: Path, stub_targets
) -> None:
    """Picker session/update must land on the wire AFTER the newSession response.

    Some ACP clients (notably Zed) drop session/update notifications that
    arrive for a sessionId they have not yet seen in a newSession /
    loadSession response. ``_enter_picker_mode`` defers the notification
    via ``_schedule_after_response`` so the response writes first.

    Regression guard for that ordering — relies on ``_RpcClient.arrival_log``
    which records every frame in read order.
    """
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=1, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-order", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            # Wait for the notification to arrive too, then inspect order.
            await client.next_notification()
            kinds = [kind for kind, _ in client.arrival_log]
            # First two frames after newSession must be response then
            # notification. Earlier connection-setup frames (none today)
            # would precede them but the relative order is what matters.
            response_index = kinds.index("response")
            notification_index = kinds.index("notification")
            assert response_index < notification_index, (
                f"response should arrive before notification; "
                f"arrival_log={client.arrival_log}"
            )
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_new_auto_bind_notifications_arrive_after_response(
    short_data_dir: Path, stub_targets
) -> None:
    """Single-target auto-bind: binding confirmation + title arrive AFTER response.

    Companion to the picker ordering test — auto-bind also introduces
    a fresh sessionId in its response, so any ``session/update`` sent
    inline would be dropped by clients that haven't seen the id yet.
    ``_auto_bind`` defers via ``_schedule_after_response`` ⇒
    ``_post_bind_setup``.
    """
    stub_targets(
        [_make_sample(task="solo", sample_id="s1", epoch=0, session_id="uuid-only")]
    )
    async with acp_server(eval_id="evt-auto-order", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            # Drain the binding confirmation; further notifications
            # (session_info title) may also arrive but the relative
            # ordering vs the response is what we care about.
            await client.next_notification()
            kinds = [kind for kind, _ in client.arrival_log]
            response_index = kinds.index("response")
            notification_index = kinds.index("notification")
            assert response_index < notification_index, (
                f"newSession auto-bind response should arrive before "
                f"any notifications; arrival_log={client.arrival_log}"
            )
        finally:
            await client.close()


async def test_load_session_stops_old_forwarders_before_changing_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``session/load`` must tear down prior forwarders SYNCHRONOUSLY before rebind.

    The defer-after-response fix moved binding confirmation, title, and
    new-forwarder startup into ``_post_bind_setup``. If ``_stop_forwarders``
    rode along inside the deferred task, the old forwarder would keep
    publishing during the gap — and ``Forwarders._rewrite_session_id``
    reads ``state.wire_session_id`` at notification time, so old-target
    events would be rewritten under the new wire id and leak as if they
    came from the new session.

    Pinned property: by the time ``_stop_forwarders`` is called,
    ``state.binding`` is still the OLD ``Bound``; only after stop
    completes does the binding flip.
    """
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    old_bound = Bound(wire_session_id="old-uuid", target_session_id="old-uuid")
    handler.state.binding = old_bound

    monkeypatch.setattr(
        "inspect_ai.agent._acp.connection.list_picker_targets",
        lambda: [PickerTarget(session_id="new-uuid", task="t", sample_id="s", epoch=0)],
    )

    binding_at_stop: Any = None

    async def _spy_stop() -> None:
        nonlocal binding_at_stop
        binding_at_stop = handler.state.binding

    monkeypatch.setattr(handler, "_stop_forwarders", _spy_stop)
    # Block the deferred work so this test exercises only the synchronous path.
    monkeypatch.setattr(handler, "_schedule_after_response", MagicMock())

    await handler.load_session(cwd="/tmp", session_id="new-uuid")

    assert binding_at_stop == old_bound, (
        "_stop_forwarders must run BEFORE state.binding is mutated; "
        f"saw {binding_at_stop} at stop time"
    )
    assert handler.state.binding == Bound(
        wire_session_id="new-uuid", target_session_id="new-uuid"
    )


async def test_auto_bind_stops_old_forwarders_before_changing_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-bind has the same synchronous-stop-before-rebind requirement.

    Counterpart to the ``load_session`` test — covers the single-target
    ``session/new`` path through ``_auto_bind``.
    """
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    old_bound = Bound(wire_session_id="old-uuid", target_session_id="old-uuid")
    handler.state.binding = old_bound
    target = PickerTarget(session_id="new-uuid", task="t", sample_id="s", epoch=0)

    binding_at_stop: Any = None

    async def _spy_stop() -> None:
        nonlocal binding_at_stop
        binding_at_stop = handler.state.binding

    monkeypatch.setattr(handler, "_stop_forwarders", _spy_stop)
    monkeypatch.setattr(handler, "_schedule_after_response", MagicMock())

    await handler._auto_bind(target)

    assert binding_at_stop == old_bound, (
        "_stop_forwarders must run BEFORE state.binding is mutated; "
        f"saw {binding_at_stop} at stop time"
    )
    assert handler.state.binding == Bound(
        wire_session_id="new-uuid", target_session_id="new-uuid"
    )


async def test_post_bind_setup_noops_when_generation_advanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale deferred ``_post_bind_setup`` must no-op when generation advanced.

    Race scenario: client calls ``session/load(uuid-a)``, then immediately
    ``session/load(uuid-b)`` before the first deferred task runs. Each
    bind handler increments ``_bind_generation`` under ``_bind_lock``,
    so the stale deferred task captures a generation that no longer
    matches the current one. ``_post_bind_setup`` checks this under
    the lock and bails before calling notify or start.

    Exercised directly here rather than via interleaved socket traffic —
    the live race window is small and non-deterministic.
    """
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    target_a = PickerTarget(session_id="uuid-a", task="t", sample_id="s", epoch=0)

    # Simulate the first bind capturing generation 1.
    handler._bind_generation = 1
    captured_gen = 1
    # Then a concurrent rebind advances the counter to 2.
    handler._bind_generation = 2

    locked_called = False

    async def _spy_locked(target: Any) -> None:
        nonlocal locked_called
        locked_called = True

    monkeypatch.setattr(handler, "_post_bind_setup_locked", _spy_locked)

    await handler._post_bind_setup(target_a, captured_gen)

    assert not locked_called, (
        "stale generation must skip the locked setup (no notify, no start)"
    )


async def test_post_bind_setup_proceeds_when_generation_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching generation should delegate to ``_post_bind_setup_locked``."""
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    target = PickerTarget(session_id="uuid-a", task="t", sample_id="s", epoch=0)

    handler._bind_generation = 1

    locked_args: list[Any] = []

    async def _spy_locked(t: Any) -> None:
        locked_args.append(t)

    monkeypatch.setattr(handler, "_post_bind_setup_locked", _spy_locked)

    await handler._post_bind_setup(target, 1)

    assert locked_args == [target], (
        "matching generation must delegate to _post_bind_setup_locked"
    )


async def test_forwarders_uses_immutable_wire_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Forwarders`` must use the wire id captured at construction.

    The cross-stream race the old guards prevented is now closed at
    the source: ``Forwarders._wire_session_id`` is set in
    ``__init__`` and never re-read from ``self._state``. Even if
    ``state.wire_session_id`` mutates mid-replay (e.g. a concurrent
    rebind), semantic replay must construct notifications under the
    CAPTURED wire id, not the new one.

    Pinned by capturing the ``wire`` arg passed to
    ``ReplayTranscriptor`` (the per-event semantic mapper introduced
    by the interleaved-replay change) and asserting it's the
    constructor value rather than the post-mutation
    ``state.wire_session_id``.
    """
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    handler.state.binding = Bound(
        wire_session_id="wire-A", target_session_id="target-A"
    )

    forwarders = Forwarders(
        handler.state,
        MagicMock(),
        handler,
        target_session_id="target-A",
        wire_session_id="wire-A",
    )

    # Stub raw forwarder whose per-event replay mutates
    # state.wire_session_id via a binding swap. With the captured-wire
    # fix, this MUST NOT affect the semantic transcriptor's wire id
    # (already constructed at the top of _run_replay).
    racing_raw = MagicMock()

    async def _racing_replay_event(*_a: Any, **_kw: Any) -> None:
        handler.state.binding = Bound(
            wire_session_id="wire-B", target_session_id="target-B"
        )

    racing_raw.replay_event = _racing_replay_event
    forwarders._raw_forwarder = racing_raw

    captured_wire: list[str] = []

    class _CapturingTranscriptor:
        def __init__(self, wire: str, *, filter_subagents: bool = True) -> None:
            captured_wire.append(wire)

        def process(self, _event: Any) -> list[Any]:
            return []

    monkeypatch.setattr(
        "inspect_ai.agent._acp.session_router.ReplayTranscriptor",
        _CapturingTranscriptor,
    )
    monkeypatch.setattr(
        "inspect_ai.agent._acp.session_router._filter_subagent_events",
        lambda events: events,
    )

    await forwarders._run_replay([MagicMock()])

    assert captured_wire == ["wire-A"], (
        f"ReplayTranscriptor must receive the wire id captured in the "
        f"Forwarders constructor (wire-A), not the post-mutation "
        f"state value (wire-B); got {captured_wire}"
    )


async def test_run_replay_interleaves_raw_and_semantic_in_transcript_order() -> None:
    """Late-attach replay: raw and semantic dispatch in source order, not two passes.

    Pins the fix for the chip-ordering bug. Before this change,
    ``_run_replay`` ran raw first (all ``inspect/event`` notifications)
    then semantic (all ``session/update`` notifications), so a late
    attach after the scoring phase started would render score chips
    ABOVE the replayed conversation. With interleaved dispatch, the
    wire ordering matches the underlying transcript ordering — score
    chips land at their natural position relative to the
    message-group notifications they followed.

    Test feeds a snapshot of [agent_msg, scorer_span_begin,
    score_event, span_end] and asserts the wire receives them in
    that order, not [scorer_span_begin, score_event, span_end,
    agent_msg].
    """
    from inspect_ai.agent._acp.inspect_ext import (
        INSPECT_EVENT_METHOD,
        RAW_EVENTS_GLOB,
        RawEventForwarder,
    )
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._score import ScoreEvent
    from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model_output import (
        ChatCompletionChoice,
        ModelOutput,
    )
    from inspect_ai.scorer._metric import Score

    # Wire ordering capture: record (method, payload-marker) per call.
    captured: list[tuple[str, str]] = []

    class _CapturingConn:
        async def send_notification(self, method: str, payload: dict[str, Any]) -> None:
            # For raw events, the marker is the event-type discriminator.
            # For semantic, it's the session-update kind so we can tell
            # message chunks apart from the inspect-event firehose.
            if method == INSPECT_EVENT_METHOD:
                marker = payload.get("event") or "?"
            else:
                # session/update wraps a SessionNotification — extract
                # the update kind from the inner ``update.sessionUpdate``
                # field (camelCase on the wire via by_alias=True).
                upd = payload.get("update") or {}
                marker = upd.get("sessionUpdate") or "?"
            captured.append((method, str(marker)))

    handler = ConnectionHandler()
    handler.state.binding = Bound(
        wire_session_id="wire-x", target_session_id="target-x"
    )

    forwarders = Forwarders(
        handler.state,
        _CapturingConn(),  # type: ignore[arg-type]
        handler,
        target_session_id="target-x",
        wire_session_id="wire-x",
    )
    # Subscribe to the full firehose so every event also goes raw.
    forwarders._raw_forwarder = RawEventForwarder(
        _CapturingConn(),  # type: ignore[arg-type]
        subscription=frozenset({RAW_EVENTS_GLOB}),
    )
    # Reuse the same capturing connection so the test sees ALL
    # outbound calls (raw + semantic) in one ordered list.
    forwarders._raw_forwarder._connection = forwarders._connection

    # Build a snapshot: agent message, scoring boundary, score event,
    # scorer span end. The model event needs a non-empty completion
    # so the semantic mapper actually emits an agent message chunk.
    output = ModelOutput(
        model="m",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="hello"),
                stop_reason="stop",
            )
        ],
    )
    snapshot: list[Any] = [
        ModelEvent(
            model="m",
            input=[],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=output,
        ),
        SpanBeginEvent(id="span-s", parent_id=None, name="scorer-x", type="scorer"),
        ScoreEvent(score=Score(value="C", explanation="ok"), scorer="scorer-x"),
        SpanEndEvent(id="span-s"),
    ]

    status = await forwarders._run_replay(snapshot)
    assert not status.should_exit

    # Extract the markers in arrival order — raw + semantic mixed.
    markers = [m for _method, m in captured]
    # The model event produces agent-message chunk(s) semantically,
    # and is itself raw "model"-typed. The span_begin / span_end /
    # score are raw-only (no semantic equivalent). What we care
    # about: the agent_message_chunk must arrive BEFORE the
    # score-event raw payload, since the underlying transcript
    # ordering puts ModelEvent first.
    msg_idx = next(
        (i for i, m in enumerate(markers) if m == "agent_message_chunk"),
        None,
    )
    score_idx = next(
        (i for i, m in enumerate(markers) if m == "score"),
        None,
    )
    assert msg_idx is not None, (
        f"semantic agent_message_chunk should be in capture; got {markers}"
    )
    assert score_idx is not None, f"raw score event should be in capture; got {markers}"
    assert msg_idx < score_idx, (
        f"agent_message_chunk (i={msg_idx}) must arrive BEFORE the raw "
        f"score event (i={score_idx}) — interleaved order; got {markers}"
    )


async def test_picker_selection_holds_bind_lock_across_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_handle_picker_selection`` runs notify + start under the bind lock.

    ACP dispatches each request as its own asyncio task, so without
    serialization a concurrent ``session/load`` / ``session/new``
    could interleave with picker selection's notify / start awaits.
    The handler now holds ``_bind_lock`` for the whole rebind +
    setup tail and calls ``_post_bind_setup_locked`` inline (the
    lock-acquiring entry point would deadlock since
    ``asyncio.Lock`` is non-reentrant).

    Pinned property: while ``_post_bind_setup_locked`` is running,
    ``_bind_lock`` is held. Verified by attempting to acquire the
    lock from a concurrent task and asserting it blocks until the
    handler returns.
    """
    from acp.schema import TextContentBlock

    from inspect_ai.agent._acp.connection import PickerMode

    handler = ConnectionHandler()
    handler.connection = MagicMock()
    target = PickerTarget(session_id="uuid-target", task="t", sample_id="s", epoch=0)
    handler.state.binding = PickerMode(
        wire_session_id="control-uuid", picker_targets=[target]
    )

    monkeypatch.setattr(
        "inspect_ai.agent._acp.connection.list_picker_targets",
        lambda: [target],
    )

    lock_held_during_setup = False

    async def _spy_locked(_target: Any) -> None:
        nonlocal lock_held_during_setup
        # If we got here, the handler holds the lock — confirm by
        # checking it can't be acquired non-blockingly from this task
        # (the handler's task DOES own it; asyncio.Lock is not
        # reentrant, so even the same task gets blocked).
        lock_held_during_setup = handler._bind_lock.locked()

    monkeypatch.setattr(handler, "_post_bind_setup_locked", _spy_locked)

    await handler._handle_picker_selection([TextContentBlock(type="text", text="1")])

    assert lock_held_during_setup, (
        "picker selection must hold _bind_lock when calling _post_bind_setup_locked"
    )
    # Generation should have advanced.
    assert handler._bind_generation == 1


async def test_send_notification_if_current_skips_on_stale_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Picker notifications scheduled for a superseded bind must not fire.

    ``_enter_picker_mode`` captures the bind generation at schedule
    time and routes the deferred picker notification through
    ``_send_notification_if_current``, which re-acquires the lock
    and checks generation. A concurrent bind advancing the counter
    before the deferred task runs must drop the now-stale picker
    payload.
    """
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    handler._bind_generation = 1
    captured_gen = 1
    # Simulate a concurrent bind advancing the generation before the
    # deferred picker send runs.
    handler._bind_generation = 2

    send_calls: list[Any] = []

    async def _spy_send(notif: Any) -> None:
        send_calls.append(notif)

    monkeypatch.setattr(handler, "_send_session_update", _spy_send)

    await handler._send_notification_if_current(MagicMock(), captured_gen)

    assert send_calls == [], "stale generation must skip the picker send"


async def test_send_notification_if_current_sends_on_matching_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching generation routes the notification through ``_send_session_update``."""
    handler = ConnectionHandler()
    handler.connection = MagicMock()
    handler._bind_generation = 1
    notif = MagicMock()

    send_calls: list[Any] = []

    async def _spy_send(n: Any) -> None:
        send_calls.append(n)

    monkeypatch.setattr(handler, "_send_session_update", _spy_send)

    await handler._send_notification_if_current(notif, 1)

    assert send_calls == [notif]


async def test_picker_success_selection_bails_when_concurrent_bind_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success-branch picker selection must bail if a rebind landed mid-flight.

    Symmetric with the redisplay-branch guard: the success branch
    captures ``picker.wire_session_id`` at the top of the handler
    (outside the lock), then under the lock unconditionally
    overwrites ``state.binding``. If a concurrent
    ``session/load`` / ``session/new`` landed between selection
    resolution and lock acquisition, the stale ``picker.wire_session_id``
    would clobber the newer binding.

    Same fix as the redisplay branch — same-session check inside the
    lock, bail if it fails.

    Simulated by patching ``list_picker_targets`` (called between
    selection resolution and the lock acquisition) to mutate
    ``state.binding`` to ``Bound`` as a side effect.
    """
    from acp.schema import TextContentBlock

    from inspect_ai.agent._acp.connection import PickerMode

    handler = ConnectionHandler()
    handler.connection = MagicMock()
    target = PickerTarget(session_id="uuid-target", task="t", sample_id="s", epoch=0)
    handler.state.binding = PickerMode(
        wire_session_id="control-uuid", picker_targets=[target]
    )
    new_bound = Bound(wire_session_id="other-uuid", target_session_id="other-uuid")

    call_count = [0]

    def _racing_list_picker_targets() -> list[Any]:
        # The success branch calls ``list_picker_targets`` once to
        # confirm the resolved target is still live. Mutate the
        # binding here to simulate a concurrent rebind landing
        # between that check and the lock acquisition.
        call_count[0] += 1
        if call_count[0] == 1:
            handler.state.binding = new_bound
        return [target]  # Keep target "live" so success branch is taken.

    monkeypatch.setattr(
        "inspect_ai.agent._acp.connection.list_picker_targets",
        _racing_list_picker_targets,
    )

    stop_called = False
    setup_called = False

    async def _spy_stop() -> None:
        nonlocal stop_called
        stop_called = True

    async def _spy_setup_locked(_t: Any) -> None:
        nonlocal setup_called
        setup_called = True

    monkeypatch.setattr(handler, "_stop_forwarders", _spy_stop)
    monkeypatch.setattr(handler, "_post_bind_setup_locked", _spy_setup_locked)

    await handler._handle_picker_selection([TextContentBlock(type="text", text="1")])

    assert not stop_called, "stale success selection must not tear down newer bind"
    assert not setup_called, "stale success selection must not run post-bind setup"
    # Binding must be unchanged — the new bind is preserved.
    assert isinstance(handler.state.binding, Bound)
    assert handler.state.binding.target_session_id == new_bound.target_session_id
    # Generation must NOT have advanced — we bailed before the increment.
    assert handler._bind_generation == 0


async def test_picker_redisplay_bails_when_concurrent_bind_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redisplay path must skip its state mutation + send if a rebind landed.

    The redisplay branch of ``_handle_picker_selection`` runs inside
    ``_bind_lock`` and verifies ``state.binding`` is still a
    ``PickerMode`` with the same ``wire_session_id``. If a concurrent
    ``session/load`` / ``session/new`` mutated the binding before we
    acquired the lock, redisplay would otherwise clobber the new
    binding by re-assigning ``PickerMode``.

    Simulated by patching ``resolve_selection`` to ALSO mutate
    ``state.binding`` to ``Bound`` as a side effect — modeling the
    concurrent rebind landing between selection resolution and the
    redisplay lock acquisition.
    """
    from acp.schema import TextContentBlock

    from inspect_ai.agent._acp.connection import PickerMode

    handler = ConnectionHandler()
    handler.connection = MagicMock()
    target = PickerTarget(session_id="uuid-target", task="t", sample_id="s", epoch=0)
    # Picker is showing; the selection prompt arrives.
    handler.state.binding = PickerMode(
        wire_session_id="control-uuid", picker_targets=[target]
    )
    new_bound = Bound(wire_session_id="other-uuid", target_session_id="other-uuid")

    def _racing_resolve(*_a: Any, **_kw: Any) -> None:
        # Simulate a concurrent rebind landing between selection
        # resolution and the redisplay's lock acquisition.
        handler.state.binding = new_bound
        return None  # Bad selection → redisplay branch.

    monkeypatch.setattr(
        "inspect_ai.agent._acp.connection.resolve_selection",
        _racing_resolve,
    )

    sent: list[Any] = []

    async def _spy_send(notif: Any) -> None:
        sent.append(notif)

    monkeypatch.setattr(handler, "_send_session_update", _spy_send)

    await handler._handle_picker_selection(
        [TextContentBlock(type="text", text="bogus")]
    )

    assert sent == [], "stale redisplay must not send a notification"
    # Binding must be unchanged — the new bind is preserved.
    assert isinstance(handler.state.binding, Bound)
    assert handler.state.binding.target_session_id == new_bound.target_session_id


@skip_if_trio
async def test_concurrent_bind_handlers_serialize_under_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent bind handlers must run sequentially, not interleave.

    Fires two ``load_session`` requests as concurrent asyncio tasks
    against the same ``ConnectionHandler``. ``_bind_lock`` should
    serialize their stop + state-mutate sequences: one bind's
    handler completes its locked region before the other starts.

    Pinned via a single ordered event log: each handler emits "enter"
    on entry to the locked critical section, yields multiple times to
    invite interleaving, then emits "exit". With the lock, the log
    MUST be ``[enter, exit, enter, exit]`` — anything else (notably
    ``[enter, enter, exit, exit]``) proves the handlers interleaved.
    """
    handler = ConnectionHandler()
    handler.connection = MagicMock()

    target_a = PickerTarget(session_id="uuid-a", task="t", sample_id="sa", epoch=0)
    target_b = PickerTarget(session_id="uuid-b", task="t", sample_id="sb", epoch=0)
    monkeypatch.setattr(
        "inspect_ai.agent._acp.connection.list_picker_targets",
        lambda: [target_a, target_b],
    )

    event_log: list[str] = []
    real_stop = handler._stop_forwarders

    async def _slow_stop() -> None:
        # Caller (the bind handler) is inside ``_bind_lock`` when this
        # runs. Multiple yields invite interleaving if the lock isn't
        # actually serializing.
        event_log.append("enter")
        for _ in range(3):
            await asyncio.sleep(0)
        await real_stop()
        event_log.append("exit")

    monkeypatch.setattr(handler, "_stop_forwarders", _slow_stop)
    # Skip the deferred setup — we only care about the locked section.
    monkeypatch.setattr(handler, "_schedule_after_response", lambda *_a, **_kw: None)

    # Fire both bind handlers concurrently.
    await asyncio.gather(
        handler.load_session(cwd="/tmp", session_id="uuid-a"),
        handler.load_session(cwd="/tmp", session_id="uuid-b"),
    )

    # Strict non-interleaving: each handler's enter must be immediately
    # followed by its own exit, with no other handler's events in
    # between. Without the lock, the log would be
    # ["enter", "enter", "exit", "exit"] because both handlers would
    # yield to the event loop and run interleaved.
    assert event_log == ["enter", "exit", "enter", "exit"], (
        f"bind handlers must not interleave; saw event_log={event_log}"
    )
    assert handler._bind_generation == 2


@skip_if_trio
@unix_only
async def test_session_load_notifications_arrive_after_response(
    short_data_dir: Path, stub_targets
) -> None:
    """``session/load``: binding confirmation + title arrive AFTER response.

    Companion to the picker / auto-bind ordering tests — ``loadSession``
    is the third path whose response introduces (or re-introduces) the
    sessionId to the client. ``load_session`` defers post-bind work via
    ``_schedule_after_response`` ⇒ ``_post_bind_setup``.
    """
    stub_targets(
        [_make_sample(task="solo", sample_id="s1", epoch=0, session_id="uuid-only")]
    )
    async with acp_server(eval_id="evt-load-order", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request(
                "session/load",
                {"cwd": "/tmp", "sessionId": "uuid-only", "mcpServers": []},
            )
            await client.next_notification()
            kinds = [kind for kind, _ in client.arrival_log]
            response_index = kinds.index("response")
            notification_index = kinds.index("notification")
            assert response_index < notification_index, (
                f"loadSession response should arrive before any "
                f"notifications; arrival_log={client.arrival_log}"
            )
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_new_with_single_target_auto_binds(
    short_data_dir: Path, stub_targets
) -> None:
    """One target → response sessionId IS the target's uuid; bind confirmed."""
    stub_targets(
        [_make_sample(task="solo", sample_id="s1", epoch=0, session_id="uuid-only")]
    )
    async with acp_server(eval_id="evt-new-1", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            assert resp["result"]["sessionId"] == "uuid-only"

            notif = await client.next_notification()
            params = notif["params"]
            # The confirmation notification is keyed to the target,
            # not a separate control sessionId.
            assert params["sessionId"] == "uuid-only"
            text = params["update"]["content"]["text"]
            assert "Bound to" in text
            assert "solo" in text
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_new_with_no_targets_pushes_empty_picker(
    short_data_dir: Path, stub_targets
) -> None:
    """Zero targets → control sessionId + 'no sessions available' notification."""
    stub_targets([])
    async with acp_server(eval_id="evt-new-0", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            assert "result" in resp
            control_id = resp["result"]["sessionId"]
            assert control_id  # non-empty

            notif = await client.next_notification()
            text = notif["params"]["update"]["content"]["text"]
            assert "No sessions" in text
            # Empty list in _meta — capability-aware clients still see
            # a well-formed structure.
            assert notif["params"]["_meta"][PICKER_META_KEY] == []
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# inspect/list_sessions — direct enumeration for Inspect-aware clients
# (skips the session/new + picker-notification + _meta-parsing
# round-trip that generic ACP clients have to do)
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_inspect_list_sessions_returns_all_attachable_targets(
    short_data_dir: Path, stub_targets
) -> None:
    """Populated list with the same shape as the picker _meta payload + 'target'."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=1, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-list", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_sessions", {})
            assert "result" in resp, resp
            sessions = resp["result"]["sessions"]
            assert len(sessions) == 2
            # Per-entry shape matches the existing PICKER_META_KEY entries
            # plus a convenience 'target' field for inspect/attach.
            for sess, expected in zip(
                sessions,
                [
                    {
                        "sessionId": "uuid-a",
                        "task": "t1",
                        "sampleId": "s1",
                        "epoch": 0,
                        "agentName": None,
                        "startedAt": None,
                        "totalMessages": 0,
                        "totalTokens": 0,
                        "failsOnError": True,
                        "target": "t1/s1/0",
                    },
                    {
                        "sessionId": "uuid-b",
                        "task": "t2",
                        "sampleId": "s2",
                        "epoch": 1,
                        "agentName": None,
                        "startedAt": None,
                        "totalMessages": 0,
                        "totalTokens": 0,
                        "failsOnError": True,
                        "target": "t2/s2/1",
                    },
                ],
            ):
                assert sess == expected
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_list_sessions_empty_when_no_targets(
    short_data_dir: Path, stub_targets
) -> None:
    """Zero attachable samples → empty sessions list (not an error).

    Discovery is the prerequisite for binding; an empty list is a
    valid answer ("no samples have claimed an ACP session yet").
    """
    stub_targets([])
    async with acp_server(eval_id="evt-list-empty", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_sessions", {})
            assert resp["result"] == {"sessions": []}
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_list_sessions_does_not_require_binding(
    short_data_dir: Path, stub_targets
) -> None:
    """Method works on a fresh connection with no session/new yet.

    Pinned because list_sessions is the discovery step — making it
    require a prior bind would defeat the purpose.
    """
    stub_targets([_make_sample(task="t", sample_id="s", epoch=0, session_id="u")])
    async with acp_server(eval_id="evt-list-fresh", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            # NO initialize, NO session/new — straight to list.
            resp = await client.request("inspect/list_sessions", {})
            assert "result" in resp, resp
            assert len(resp["result"]["sessions"]) == 1
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_list_sessions_accepts_null_params(
    short_data_dir: Path, stub_targets
) -> None:
    """JSON-RPC ``params: null`` is treated the same as ``params: {}``.

    The spec allows the ``params`` member to be omitted or ``null``
    for methods that take no parameters. ``model.model_validate(None)``
    would otherwise fail for our empty :class:`ListSessionsParams`
    model — ``wrap_action_handler`` coerces ``None`` → ``{}`` to
    make the no-params form work transparently. (We test with
    ``null`` rather than truly-omitted because the existing
    ``_RpcClient.request`` always emits the params field; both
    shapes hit the same handler-level ``None`` value.)
    """
    stub_targets([_make_sample(task="t", sample_id="s", epoch=0, session_id="u")])
    async with acp_server(eval_id="evt-list-noparams", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_sessions", None)
            assert "result" in resp, resp
            assert len(resp["result"]["sessions"]) == 1
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# inspect/list_samples — superset enumeration (includes non-ACP samples)
# consumed by the Inspect TUI to surface samples whose agent hasn't
# claimed ACP. Standard ACP clients (Zed) continue to use list_sessions.
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_inspect_list_samples_returns_acp_and_non_acp(
    short_data_dir: Path, stub_targets
) -> None:
    """Both ACP-claimed and non-claimed samples appear; ``sessionId`` discriminates."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=0, session_id=None),
            _make_sample(task="t3", sample_id="s3", epoch=1, session_id="noop"),
        ]
    )
    async with acp_server(eval_id="evt-samp", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_samples", {})
            assert "result" in resp, resp
            samples = resp["result"]["samples"]
            assert len(samples) == 3
            # ACP-claimed: uuid present.
            assert samples[0]["sessionId"] == "uuid-a"
            assert samples[0]["sampleId"] == "s1"
            # Non-claimed: sessionId is None.
            assert samples[1]["sessionId"] is None
            assert samples[1]["sampleId"] == "s2"
            # Noop sentinel collapses to non-claimed (pre-claim placeholder).
            assert samples[2]["sessionId"] is None
            assert samples[2]["sampleId"] == "s3"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_list_samples_empty_when_no_samples(
    short_data_dir: Path, stub_targets
) -> None:
    """Zero active samples → empty list (not an error)."""
    stub_targets([])
    async with acp_server(eval_id="evt-samp-empty", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_samples", {})
            assert resp["result"] == {"samples": []}
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_list_samples_does_not_require_binding(
    short_data_dir: Path, stub_targets
) -> None:
    """Method works on a fresh connection — discovery doesn't require a prior bind."""
    stub_targets([_make_sample(task="t", sample_id="s", epoch=0, session_id=None)])
    async with acp_server(eval_id="evt-samp-fresh", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_samples", {})
            assert "result" in resp, resp
            assert len(resp["result"]["samples"]) == 1
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_list_samples_accepts_null_params(
    short_data_dir: Path, stub_targets
) -> None:
    """``params: null`` is treated as ``{}`` (mirrors list_sessions)."""
    stub_targets([_make_sample(task="t", sample_id="s", epoch=0, session_id="uuid")])
    async with acp_server(eval_id="evt-samp-noparams", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request("inspect/list_samples", None)
            assert "result" in resp, resp
            assert len(resp["result"]["samples"]) == 1
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# inspect/attach — direct bind via task/sample_id/epoch tuple,
# skipping the picker. Inspect-aware clients (the TUI, editors
# that already know which sample to attach to) use this to avoid the
# "browse and pick" round-trip when they have the identifier from a
# prior session.
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_inspect_attach_direct_target_auto_binds(
    short_data_dir: Path, stub_targets
) -> None:
    """target=task/sample/epoch matches an active sample → immediate bind."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=1, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-ins-new", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "inspect/attach",
                {"cwd": "/tmp", "mcpServers": [], "target": "t2/s2/1"},
            )
            assert "result" in resp, resp
            # Response carries the canonical uuid for the matched target.
            assert resp["result"]["sessionId"] == "uuid-b"
            # Binding confirmation notification lands.
            notif = await client.next_notification()
            params = notif["params"]
            assert params["sessionId"] == "uuid-b"
            assert "Bound to" in params["update"]["content"]["text"]
            assert "t2" in params["update"]["content"]["text"]
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_attach_target_with_no_match_errors(
    short_data_dir: Path, stub_targets
) -> None:
    """Unknown target → invalid_params with the available list.

    Pinned because the explicit-ask path must NEVER silently fall
    through to the picker — clients that asked for a specific sample
    should get a clear miss diagnostic, not a surprise picker
    notification.
    """
    stub_targets(
        [_make_sample(task="real", sample_id="s1", epoch=0, session_id="uuid-r")]
    )
    async with acp_server(eval_id="evt-ins-miss", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "inspect/attach",
                {"cwd": "/tmp", "mcpServers": [], "target": "ghost/sX/9"},
            )
            assert "error" in resp, resp
            assert resp["error"]["code"] == -32602
            assert "ghost/sX/9" in str(resp["error"])
            # Available list is included so the client can render a useful
            # diagnostic (or rebind to a valid option).
            data = resp["error"]["data"]
            assert "available" in data
            assert "real/s1/0" in data["available"]
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_attach_malformed_target_errors(
    short_data_dir: Path, stub_targets
) -> None:
    """Target without 3 slash-separated parts → invalid_params at parse time.

    Catches the miss before touching the picker target list — even if
    the parse succeeds-by-coincidence with garbage, the match step
    would fail; this just produces a more pointed error message.
    """
    stub_targets([_make_sample(task="t", sample_id="s", epoch=0, session_id="u")])
    async with acp_server(eval_id="evt-ins-bad", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            for bad in ("noslashes", "only/one", "epoch/not/integer"):
                resp = await client.request(
                    "inspect/attach",
                    {"cwd": "/tmp", "mcpServers": [], "target": bad},
                )
                assert "error" in resp, (bad, resp)
                assert resp["error"]["code"] == -32602, bad
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_inspect_attach_target_with_empty_sample_id(
    short_data_dir: Path, stub_targets
) -> None:
    """Sample with no explicit id (``sample.id is None``) stringifies to ``""``.

    Spec for such a sample is ``task//epoch`` (two consecutive
    slashes). Pinned because the parse uses ``rpartition`` and would
    otherwise reject the empty middle segment.
    """
    stub_targets(
        [_make_sample(task="t", sample_id="", epoch=0, session_id="uuid-empty")]
    )
    async with acp_server(eval_id="evt-ins-empty", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "inspect/attach",
                {"cwd": "/tmp", "mcpServers": [], "target": "t//0"},
            )
            assert "result" in resp, resp
            assert resp["result"]["sessionId"] == "uuid-empty"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# session/load — direct bind on known id; invalid_params on unknown
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_session_load_known_id_binds_directly(
    short_data_dir: Path, stub_targets
) -> None:
    """Known sessionId → LoadSessionResponse + binding confirmation notification."""
    stub_targets(
        [_make_sample(task="t", sample_id="s", epoch=0, session_id="uuid-known")]
    )
    async with acp_server(eval_id="evt-load-known", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/load",
                {"cwd": "/tmp", "mcpServers": [], "sessionId": "uuid-known"},
            )
            assert "result" in resp

            notif = await client.next_notification()
            params = notif["params"]
            assert params["sessionId"] == "uuid-known"
            assert "Bound to" in params["update"]["content"]["text"]
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_load_unknown_id_returns_invalid_params(
    short_data_dir: Path, stub_targets
) -> None:
    """Unknown sessionId → invalid_params error, no fallback to picker.

    Clients that want the picker call session/new instead.
    """
    stub_targets(
        [_make_sample(task="t", sample_id="s", epoch=0, session_id="uuid-other")]
    )
    async with acp_server(eval_id="evt-load-unknown", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/load",
                {"cwd": "/tmp", "mcpServers": [], "sessionId": "uuid-nope"},
            )
            assert "error" in resp
            # JSON-RPC 2.0 invalid-params code.
            assert resp["error"]["code"] == -32602
            assert "unknown session_id" in resp["error"]["data"]["reason"]
            # No notification should have been pushed.
            await asyncio.sleep(0.05)
            assert not client.notification_pending()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# session/prompt — picker selection by index and uuid; bad selection;
# bound-mode placeholder
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_picker_selection_by_index_rebinds(
    short_data_dir: Path, stub_targets
) -> None:
    """After picker, `prompt` with text '2' selects the second target.

    Contract: the confirmation `session/update` carries the
    **control** sessionId (the one the client got from `session/new`),
    not the target's id — the design says the client's sessionId is
    stable across rebind. The target id is exposed via `_meta`.
    """
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-pick-idx", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            # Drain the picker notification.
            await client.next_notification()

            # Send the selection as a prompt with a text block.
            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": control_id,
                    "prompt": [{"type": "text", "text": "2"}],
                },
            )
            assert prompt_resp["result"]["stopReason"] == "end_turn"

            # Confirmation notification keeps the control sessionId so
            # the client's session-id-keyed routing keeps working.
            confirm = await client.next_notification()
            assert confirm["params"]["sessionId"] == control_id
            assert "Bound to" in confirm["params"]["update"]["content"]["text"]
            # Target id is exposed via _meta so capability-aware clients
            # can correlate to (task, sample_id, epoch).
            meta_targets = confirm["params"]["_meta"][PICKER_META_KEY]
            assert len(meta_targets) == 1
            assert meta_targets[0]["sessionId"] == "uuid-b"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_picker_selection_by_uuid_rebinds(
    short_data_dir: Path, stub_targets
) -> None:
    """After picker, `prompt` with uuid text selects by id regardless of index."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-pick-uuid", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            await client.next_notification()  # drain picker

            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": control_id,
                    "prompt": [{"type": "text", "text": "uuid-a"}],
                },
            )
            assert prompt_resp["result"]["stopReason"] == "end_turn"

            confirm = await client.next_notification()
            # Wire sessionId preserved across rebind.
            assert confirm["params"]["sessionId"] == control_id
            assert (
                confirm["params"]["_meta"][PICKER_META_KEY][0]["sessionId"] == "uuid-a"
            )
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_picker_bad_selection_redisplays_picker(
    short_data_dir: Path, stub_targets
) -> None:
    """A selection that doesn't parse re-pushes the picker so the client can retry."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-pick-bad", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            await client.next_notification()  # drain initial picker

            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": control_id,
                    "prompt": [{"type": "text", "text": "99"}],
                },
            )
            assert prompt_resp["result"]["stopReason"] == "end_turn"

            # Second picker notification re-pushed (text contains "1." and "2.").
            redisplay = await client.next_notification()
            text = redisplay["params"]["update"]["content"]["text"]
            assert "1." in text and "2." in text
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_bound_mode_prompt_with_unreachable_target_returns_internal_error(
    short_data_dir: Path, stub_targets
) -> None:
    """A bound prompt whose target can't be looked up returns internal_error.

    Phase 9's test was a placeholder asserting `method_not_found` for
    bound-mode prompts. Phase 10 forwards them to the bound target's
    ``submit_user_message`` via :func:`_find_live_session`, which walks
    the real ``active_samples()`` registry. The dispatch tests use
    ``stub_targets`` (monkeypatched at ``picker.active_samples``)
    which does NOT plug into the registry the forwarder reads, so
    targets are present at picker time but unreachable at forward
    time — surfaces as ``internal_error`` with a clear reason. Real
    forwarding to a live ``LiveAcpTransport`` is exercised in
    ``test_server_forwarding.py``.
    """
    stub_targets(
        [_make_sample(task="solo", sample_id="s", epoch=0, session_id="uuid-only")]
    )
    async with acp_server(eval_id="evt-bound", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            assert resp["result"]["sessionId"] == "uuid-only"
            await client.next_notification()  # drain bind confirmation

            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": "uuid-only",
                    "prompt": [{"type": "text", "text": "hello target"}],
                },
            )
            assert "error" in prompt_resp
            # internal_error from the _find_live_session miss.
            assert prompt_resp["error"]["code"] == -32603
            assert (
                prompt_resp["error"]["data"]["reason"]
                == "bound session no longer active"
            )
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_cancel_notification_silently_accepted(
    short_data_dir: Path, stub_targets
) -> None:
    """`session/cancel` notification is silently accepted (no response either way).

    Phase 10 will forward it to the target's `cancel_current_turn`;
    Phase 9 just verifies the dispatch doesn't crash and no error
    notification gets pushed back.
    """
    stub_targets(
        [_make_sample(task="t", sample_id="s", epoch=0, session_id="uuid-only")]
    )
    async with acp_server(eval_id="evt-cancel", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # drain bind confirmation

            # Notifications don't return responses; send + small wait.
            await client.notify("session/cancel", {"sessionId": "uuid-only"})
            await asyncio.sleep(0.05)
            # No notification queued in response to our cancel.
            assert not client.notification_pending()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# session_id validation on prompt / cancel
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_prompt_with_wrong_session_id_returns_invalid_params(
    short_data_dir: Path, stub_targets
) -> None:
    """`session/prompt` with a sessionId that doesn't match the wire id errors.

    Prevents a confused / misbehaving client from sneaking a prompt
    onto the wrong session via this connection. The wire sessionId is
    pinned by the connection's most recent ``session/new`` /
    ``session/load`` response.
    """
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-wrong-prompt", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            await client.next_notification()  # drain picker

            # Send selection with a sessionId that doesn't match the
            # connection's wire id (here: the target id we plan to pick).
            bad = await client.request(
                "session/prompt",
                {
                    "sessionId": "uuid-a",
                    "prompt": [{"type": "text", "text": "1"}],
                },
            )
            assert "error" in bad
            assert bad["error"]["code"] == -32602
            assert "expected" in bad["error"]["data"]
            assert bad["error"]["data"]["expected"] == control_id
            # No notification fired since the request errored at the
            # validation gate (no picker re-display, no rebind).
            await asyncio.sleep(0.05)
            assert not client.notification_pending()
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_cancel_with_wrong_session_id_is_silently_dropped(
    short_data_dir: Path, stub_targets
) -> None:
    """`session/cancel` notification with a foreign sessionId is silently dropped.

    Notifications can't return errors, so the safe thing is to refuse
    to act on the cancel rather than crash or accidentally route it.
    Phase 10's cancel forwarding will inherit this validation.
    """
    stub_targets(
        [_make_sample(task="t", sample_id="s", epoch=0, session_id="uuid-only")]
    )
    async with acp_server(eval_id="evt-wrong-cancel", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # drain bind confirmation

            # Send a cancel for some other session id — should be a no-op.
            await client.notify("session/cancel", {"sessionId": "uuid-someone-else"})
            await asyncio.sleep(0.05)
            # Connection is still alive and the wrong cancel didn't
            # surface any error or notification.
            assert not client.notification_pending()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Picker snapshot: numeric selection resolves against the displayed list
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_picker_numeric_selection_pins_to_snapshot_under_reorder(
    short_data_dir: Path, monkeypatch
) -> None:
    """Numeric `"1"` binds to the target the client SAW at picker-push time.

    Race: the active-sample list reorders between the picker push
    (first `active_samples()` call) and the selection prompt (second
    + third calls — one in `_handle_picker_selection`'s liveness
    re-check). Without a snapshot, the fresh enumeration would shift
    the meaning of "1"; with the snapshot, "1" stays pinned to the
    displayed first target.

    Target uuid-A is still LIVE in the reshuffled list — just at a
    different index — so the liveness re-check passes and we bind.
    """
    initial = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-A"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-B"),
        _make_sample(task="t3", sample_id="s3", epoch=0, session_id="uuid-C"),
    ]
    # Reshuffled list still contains A but at position 2; without the
    # snapshot the client's "1" would resolve to C.
    reshuffled = [
        _make_sample(task="t3", sample_id="s3", epoch=0, session_id="uuid-C"),
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-A"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-B"),
    ]
    call_count = {"n": 0}

    def _changing_active_samples() -> list[Any]:
        call_count["n"] += 1
        return initial if call_count["n"] == 1 else reshuffled

    monkeypatch.setattr(picker, "active_samples", _changing_active_samples)

    async with acp_server(eval_id="evt-snap-reorder", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            notif = await client.next_notification()
            shown = [t["sessionId"] for t in notif["params"]["_meta"][PICKER_META_KEY]]
            assert shown == ["uuid-A", "uuid-B", "uuid-C"]

            await client.request(
                "session/prompt",
                {
                    "sessionId": control_id,
                    "prompt": [{"type": "text", "text": "1"}],
                },
            )
            confirm = await client.next_notification()
            target = confirm["params"]["_meta"][PICKER_META_KEY][0]
            assert target["sessionId"] == "uuid-A", (
                "Snapshot regression: selection resolved against fresh "
                "active_samples() instead of the list pushed to the client."
            )
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_picker_selection_of_finished_target_redisplays(
    short_data_dir: Path, monkeypatch
) -> None:
    """If the picked target has finished before the selection arrives, redisplay.

    Without the post-snapshot liveness check, the handler would set
    ``target_session_id`` to a sessionId no live agent owns. Phase 10
    would then have nothing to forward prompts/cancels to. The
    correct behavior is to push a fresh picker with the current
    target list so the client can pick a still-live target.
    """
    initial = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-A"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-B"),
        _make_sample(task="t3", sample_id="s3", epoch=0, session_id="uuid-C"),
    ]
    # uuid-A has finished; new sample uuid-D started.
    after_finish = [
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-B"),
        _make_sample(task="t3", sample_id="s3", epoch=0, session_id="uuid-C"),
        _make_sample(task="t4", sample_id="s4", epoch=0, session_id="uuid-D"),
    ]
    call_count = {"n": 0}

    def _changing_active_samples() -> list[Any]:
        call_count["n"] += 1
        return initial if call_count["n"] == 1 else after_finish

    monkeypatch.setattr(picker, "active_samples", _changing_active_samples)

    async with acp_server(eval_id="evt-snap-stale", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            await client.next_notification()  # drain initial picker

            # Client picks "1" — snapshot says uuid-A, but uuid-A is gone.
            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": control_id,
                    "prompt": [{"type": "text", "text": "1"}],
                },
            )
            assert prompt_resp["result"]["stopReason"] == "end_turn"

            # Redisplay, not confirmation. Distinguish by content:
            # a redisplay shows the picker list, a confirmation shows
            # "Bound to ...".
            redisplay = await client.next_notification()
            text = redisplay["params"]["update"]["content"]["text"]
            assert "Bound to" not in text
            shown = [
                t["sessionId"] for t in redisplay["params"]["_meta"][PICKER_META_KEY]
            ]
            assert shown == ["uuid-B", "uuid-C", "uuid-D"]
            assert "uuid-A" not in shown
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Multi-connection isolation
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_concurrent_connections_keep_separate_state(
    short_data_dir: Path, stub_targets
) -> None:
    """Two clients can pick different targets without interfering."""
    stub_targets(
        [
            _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
            _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-b"),
        ]
    )
    async with acp_server(eval_id="evt-multi-iso", transport=True) as server:
        assert server is not None
        c1 = await _connect(server)
        c2 = await _connect(server)
        try:
            r1 = await c1.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            r2 = await c2.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            # Different control sessionIds (per-connection state).
            assert r1["result"]["sessionId"] != r2["result"]["sessionId"]
            await c1.next_notification()
            await c2.next_notification()

            # Each picks a different target.
            await c1.request(
                "session/prompt",
                {
                    "sessionId": r1["result"]["sessionId"],
                    "prompt": [{"type": "text", "text": "1"}],
                },
            )
            await c2.request(
                "session/prompt",
                {
                    "sessionId": r2["result"]["sessionId"],
                    "prompt": [{"type": "text", "text": "2"}],
                },
            )
            confirm1 = await c1.next_notification()
            confirm2 = await c2.next_notification()
            # Each connection's confirmation carries its OWN control
            # sessionId (wire id), not the picked target's id —
            # post-rebind the wire id stays stable from the client POV.
            assert confirm1["params"]["sessionId"] == r1["result"]["sessionId"]
            assert confirm2["params"]["sessionId"] == r2["result"]["sessionId"]
            # Underlying targets are accessible via _meta.
            assert (
                confirm1["params"]["_meta"][PICKER_META_KEY][0]["sessionId"] == "uuid-a"
            )
            assert (
                confirm2["params"]["_meta"][PICKER_META_KEY][0]["sessionId"] == "uuid-b"
            )
        finally:
            await c1.close()
            await c2.close()
