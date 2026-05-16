"""Phase 10 integration tests for the per-connection forwarder.

Exercises the full inbound/outbound forwarding pipeline against a
real :class:`_LiveAcpSession` registered as an active sample.
``_find_live_session`` (in ``_server``) walks the ``active_samples()``
list — these tests patch that list so the forwarder can resolve a
target. Notifications go over a real AF_UNIX loopback socket and
through ``acp.connection.Connection``'s framing.

Coverage:
- session/prompt forwarding to ``submit_user_message``
- session/cancel forwarding to ``cancel_current_turn``
- Outbound semantic forwarding via the per-connection forwarder
- Plan-policy live transformation for Zed / Toad clients
- Forwarder cleanup on disconnect
- Replay-on-attach with cap + elision
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
from acp.helpers import (
    session_notification,
    start_tool_call,
    text_block,
    update_agent_message,
    update_tool_call,
)
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp import _picker
from inspect_ai.agent._acp._server import (
    ELISION_THRESHOLD_BYTES,
    REPLAY_MAX_EVENTS,
    acp_server,
)
from inspect_ai.agent._acp._session import _LiveAcpSession
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def short_data_dir(monkeypatch):
    """Short /tmp data dir so AF_UNIX paths fit in 104 chars on macOS."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_fwd_", dir="/tmp"))

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


def _make_active_sample(
    *, task: str, sample_id: str, epoch: int, acp_session: Any
) -> Any:
    """Build a stub ActiveSample with the required fields the picker reads."""
    sample = MagicMock()
    sample.id = sample_id
    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    # Explicit None on the new fields so MagicMock doesn't auto-wrap
    # them (would otherwise blow up JSON serialization downstream).
    active.agent_name = None
    active.started = None
    active.total_tokens = 0
    active.acp_session = acp_session
    return active


@pytest.fixture
def register_target(monkeypatch):
    """Patch both `_picker.active_samples` AND `_samples.active_samples`.

    `_picker.active_samples` is the local import the picker uses; the
    forwarder's `_find_live_session` imports `active_samples` from
    `inspect_ai.log._samples` at call time, so we patch both to keep
    them consistent.
    """

    def _register(*targets: Any) -> None:
        monkeypatch.setattr(_picker, "active_samples", lambda: list(targets))
        monkeypatch.setattr(
            "inspect_ai.log._samples.active_samples",
            lambda: list(targets),
        )

    return _register


# ---------------------------------------------------------------------------
# Minimal JSON-RPC client (line-oriented)
# ---------------------------------------------------------------------------


class _RpcClient:
    """Tiny line-oriented JSON-RPC 2.0 client.

    Sends requests, awaits the matching response, queues incoming
    notifications. Runs a background reader task while open.
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


unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


async def _connect(server: Any) -> _RpcClient:
    reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
    return _RpcClient(reader, writer)


def _make_live_session_with_transcript() -> tuple[_LiveAcpSession, Transcript]:
    """Build a _LiveAcpSession with a real Transcript wired up.

    Bypasses ``__aenter__`` (which would also try to attach the Phase
    6 router via ``transcript()`` and register on the active sample).
    For Phase 10 forwarder tests we want the session and its
    transcript without any extra coupling.
    """
    session = _LiveAcpSession()
    tr = Transcript()
    session._transcript = tr
    return session, tr


async def _initialize(
    client: _RpcClient, *, client_name: str = "test", meta: dict[str, Any] | None = None
) -> None:
    """Run the ACP initialize handshake with optional capability flags."""
    params: dict[str, Any] = {
        "protocolVersion": 1,
        "clientInfo": {"name": client_name, "version": "0.0"},
    }
    if meta is not None:
        params["clientCapabilities"] = {"_meta": meta}
    await client.request("initialize", params)


async def _drain_bind_preamble(client: _RpcClient) -> None:
    """Drain the two notifications every successful bind emits.

    1. ``AgentMessageChunk`` — picker confirmation from ``_notify_binding``
    2. ``SessionInfoUpdate`` — Phase 2 title from ``_send_session_info_title``

    Replaces the older single ``next_notification()  # drain bind
    confirmation`` pattern that no longer covers all bind-time output.
    """
    await client.next_notification()  # AgentMessageChunk
    await client.next_notification()  # SessionInfoUpdate


# ---------------------------------------------------------------------------
# Inbound forwarding — session/prompt
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_session_prompt_forwards_to_submit_user_message(
    short_data_dir: Path, register_target
) -> None:
    """A bound `session/prompt` calls submit_user_message on the live target."""
    session, _tr = _make_live_session_with_transcript()
    # Spy on submit_user_message so we can verify what got forwarded.
    submit_calls: list[Any] = []
    session.submit_user_message = lambda msg: submit_calls.append(msg)  # type: ignore[method-assign]

    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-prompt-fwd", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            target_id = resp["result"]["sessionId"]
            await _drain_bind_preamble(client)

            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": target_id,
                    "prompt": [{"type": "text", "text": "hello agent"}],
                },
            )
            assert prompt_resp["result"]["stopReason"] == "end_turn"

            assert len(submit_calls) == 1
            assert submit_calls[0].content == "hello agent"
            assert submit_calls[0].source == "operator"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_cancel_notification_forwards_to_cancel_current_turn(
    short_data_dir: Path, register_target
) -> None:
    """A bound `session/cancel` notification calls cancel_current_turn."""
    session, _tr = _make_live_session_with_transcript()
    cancel_calls: list[None] = []
    session.cancel_current_turn = lambda: cancel_calls.append(None)  # type: ignore[method-assign]

    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-cancel-fwd", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            target_id = resp["result"]["sessionId"]
            await _drain_bind_preamble(client)

            await client.notify("session/cancel", {"sessionId": target_id})
            # Give the server a beat to dispatch the notification.
            await asyncio.sleep(0.05)
            assert len(cancel_calls) == 1
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Outbound semantic forwarding
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_session_update_published_on_bus_reaches_client(
    short_data_dir: Path, register_target
) -> None:
    """`target.publish(notif)` reaches the bound client as session/update."""
    session, _tr = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-pub-fwd", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            target_id = resp["result"]["sessionId"]
            await _drain_bind_preamble(client)

            # Publish a synthetic notification on the target's bus.
            session.publish(
                session_notification(
                    target_id, update_agent_message(text_block("hi from agent"))
                )
            )

            notif = await client.next_notification()
            assert notif["method"] == "session/update"
            assert notif["params"]["sessionId"] == target_id
            assert notif["params"]["update"]["sessionUpdate"] == "agent_message_chunk"
            assert notif["params"]["update"]["content"]["text"] == "hi from agent"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Plan-policy live transformation
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_plan_capable_client_receives_plan_update(
    short_data_dir: Path, register_target
) -> None:
    """Zed client + update_plan tool → client gets AgentPlanUpdate (not tool-call)."""
    session, _tr = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-plan-zed", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, client_name="zed")
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            target_id = resp["result"]["sessionId"]
            await _drain_bind_preamble(client)

            # Tool starts (in_progress) with raw_input — should be suppressed.
            session.publish(
                session_notification(
                    target_id,
                    start_tool_call(
                        tool_call_id="tc1",
                        title="update_plan",
                        status="in_progress",
                        raw_input={
                            "plan": [{"step": "do thing", "status": "in_progress"}]
                        },
                    ),
                )
            )
            # Then completes — should fire AgentPlanUpdate.
            session.publish(
                session_notification(
                    target_id, update_tool_call(tool_call_id="tc1", status="completed")
                )
            )

            notif = await client.next_notification()
            assert notif["params"]["update"]["sessionUpdate"] == "plan"
            entries = notif["params"]["update"]["entries"]
            assert len(entries) == 1
            assert entries[0]["content"] == "do thing"
            # Confirm NO tool-call notification leaked through.
            await asyncio.sleep(0.05)
            assert not client.notification_pending()
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_non_plan_capable_client_receives_standard_tool_call(
    short_data_dir: Path, register_target
) -> None:
    """Unknown client (no opt-in) + update_plan tool → standard tool-call notif."""
    session, _tr = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-plan-nocap", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, client_name="some-editor")
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            target_id = resp["result"]["sessionId"]
            await _drain_bind_preamble(client)

            session.publish(
                session_notification(
                    target_id,
                    start_tool_call(
                        tool_call_id="tc1",
                        title="update_plan",
                        status="in_progress",
                        raw_input={"plan": [{"step": "x", "status": "pending"}]},
                    ),
                )
            )

            notif = await client.next_notification()
            assert notif["params"]["update"]["sessionUpdate"] == "tool_call"
            assert notif["params"]["update"]["title"] == "update_plan"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_plan_optin_via_meta_works_for_unknown_client(
    short_data_dir: Path, register_target
) -> None:
    """Unknown client with `_meta[inspect.plan_rendering]: true` gets the Plan."""
    session, _tr = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-plan-meta", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(
                client,
                client_name="custom-cli",
                meta={"inspect.plan_rendering": True},
            )
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            target_id = resp["result"]["sessionId"]
            await _drain_bind_preamble(client)

            session.publish(
                session_notification(
                    target_id,
                    start_tool_call(
                        tool_call_id="tc1",
                        title="todo_write",
                        status="completed",
                        raw_input={"todos": [{"content": "x", "status": "completed"}]},
                    ),
                )
            )
            notif = await client.next_notification()
            assert notif["params"]["update"]["sessionUpdate"] == "plan"
            assert notif["params"]["update"]["entries"][0]["content"] == "x"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Forwarder cleanup
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_forwarder_detaches_subscriber_on_disconnect(
    short_data_dir: Path, register_target
) -> None:
    """When the client disconnects, the forwarder detaches from target.publish()."""
    session, _tr = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-cleanup", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()
            # One subscriber registered for this connection.
            assert len(session._subscribers) == 1
        finally:
            await client.close()
        # Give the server's connection cleanup a beat to run.
        await asyncio.sleep(0.1)
        assert len(session._subscribers) == 0


# ---------------------------------------------------------------------------
# Replay-on-attach
# ---------------------------------------------------------------------------


def _model_event_with_text(text: str) -> ModelEvent:
    """Build a ModelEvent that the router maps to a single text chunk."""
    return ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput(
            model="mockllm/model",
            choices=[ChatCompletionChoice(message=ChatMessageAssistant(content=text))],
        ),
    )


def _tool_event(*, tool_id: str, function: str, arguments: dict[str, Any]) -> ToolEvent:
    """Build a completed ToolEvent (no error)."""
    return ToolEvent(id=tool_id, function=function, arguments=arguments, pending=None)


@skip_if_trio
@unix_only
async def test_replay_emits_recent_history_before_live(
    short_data_dir: Path, register_target
) -> None:
    """A late attach receives prior transcript history as replayed session/updates."""
    session, tr = _make_live_session_with_transcript()
    # Pre-populate with 3 ModelEvents.
    for i in range(3):
        tr._event(_model_event_with_text(f"chunk-{i}"))

    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-replay", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await _drain_bind_preamble(client)

            # Now read replayed notifications.
            texts: list[str] = []
            for _ in range(3):
                notif = await client.next_notification()
                texts.append(notif["params"]["update"]["content"]["text"])
            assert texts == ["chunk-0", "chunk-1", "chunk-2"]
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_replay_caps_to_max_events(short_data_dir: Path, register_target) -> None:
    """Pre-populate beyond the cap; replay surfaces only the last N events."""
    session, tr = _make_live_session_with_transcript()
    # Pre-populate with REPLAY_MAX_EVENTS + 20 events. Each maps to
    # one notification.
    total = REPLAY_MAX_EVENTS + 20
    for i in range(total):
        tr._event(_model_event_with_text(f"chunk-{i}"))

    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-replay-cap", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await _drain_bind_preamble(client)

            # Drain everything available with a short timeout.
            received: list[str] = []
            try:
                while True:
                    notif = await client.next_notification(timeout=0.5)
                    if notif["method"] != "session/update":
                        continue
                    update = notif["params"]["update"]
                    if update.get("sessionUpdate") == "agent_message_chunk":
                        received.append(update["content"]["text"])
            except asyncio.TimeoutError:
                pass
            # Replay surfaces last REPLAY_MAX_EVENTS events.
            assert len(received) == REPLAY_MAX_EVENTS
            # First replayed is the (total - REPLAY_MAX_EVENTS)-th event.
            assert received[0] == f"chunk-{total - REPLAY_MAX_EVENTS}"
            assert received[-1] == f"chunk-{total - 1}"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_replay_elides_oversized_tool_call_raw_input(
    short_data_dir: Path, register_target
) -> None:
    """Tool-call raw_input larger than the threshold is replaced with an elision marker."""
    session, tr = _make_live_session_with_transcript()
    big_blob = "x" * (ELISION_THRESHOLD_BYTES + 1000)
    tr._event(
        _tool_event(
            tool_id="tc-big",
            function="some_tool",
            arguments={"payload": big_blob},
        )
    )

    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-replay-elide", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await _drain_bind_preamble(client)

            notif = await client.next_notification()
            assert notif["params"]["update"]["sessionUpdate"] == "tool_call"
            raw_input = notif["params"]["update"]["rawInput"]
            assert raw_input.get("_inspect.elided") is True
            assert raw_input["_inspect.original_size"] > ELISION_THRESHOLD_BYTES
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_replay_applies_plan_policy(
    short_data_dir: Path, register_target
) -> None:
    """Replayed update_plan tool event surfaces as AgentPlanUpdate for plan-capable client."""
    session, tr = _make_live_session_with_transcript()
    tr._event(
        _tool_event(
            tool_id="tc-plan",
            function="update_plan",
            arguments={"plan": [{"step": "replayed step", "status": "completed"}]},
        )
    )
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-replay-plan", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, client_name="zed")
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await _drain_bind_preamble(client)

            notif = await client.next_notification()
            update = notif["params"]["update"]
            assert update["sessionUpdate"] == "plan"
            assert update["entries"][0]["content"] == "replayed step"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_replay_then_live_ordering(short_data_dir: Path, register_target) -> None:
    """Replayed notifications arrive before live ones published after bind."""
    session, tr = _make_live_session_with_transcript()
    tr._event(_model_event_with_text("historical-1"))
    tr._event(_model_event_with_text("historical-2"))
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-replay-order", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await _drain_bind_preamble(client)

            # Publish a LIVE notification immediately after bind. The
            # client's first two semantic notifications should still
            # be the replayed historical pair.
            session.publish(
                session_notification(
                    session.session_id, update_agent_message(text_block("live-1"))
                )
            )

            seen: list[str] = []
            for _ in range(3):
                notif = await client.next_notification()
                seen.append(notif["params"]["update"]["content"]["text"])
            assert seen == ["historical-1", "historical-2", "live-1"]
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# P1 regression: live forwarder rewrites session_id to wire id
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_picker_selection_live_forwarding_uses_wire_session_id(
    short_data_dir: Path, register_target
) -> None:
    """After picker selection, live notifications arrive keyed to the wire id.

    The Phase 6 router publishes ``SessionNotification`` keyed to the
    target's ``_LiveAcpSession.session_id``. After a picker selection
    the connection's wire id is the synthetic control id minted at
    ``session/new`` time — it differs from the chosen target's id.
    The forwarder must rewrite the outbound notification's session_id
    to the wire id so the client keeps seeing the id it knows.

    Regression: the auto-bind / direct loadSession tests would pass
    even without rewriting (wire id == target id in those paths);
    only the picker selection exercises the divergence.
    """
    # Two real live targets so the picker is shown.
    target_a, _tr_a = _make_live_session_with_transcript()
    target_b, _tr_b = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(
            task="task-a", sample_id="s-a", epoch=0, acp_session=target_a
        ),
        _make_active_sample(
            task="task-b", sample_id="s-b", epoch=0, acp_session=target_b
        ),
    )
    async with acp_server(eval_id="evt-pick-fwd-wire", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            # Picker shown.
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            # Sanity: control id is not equal to either target id.
            assert control_id != target_a.session_id
            assert control_id != target_b.session_id
            await client.next_notification()  # drain picker

            # Select target_a via "1".
            await client.request(
                "session/prompt",
                {
                    "sessionId": control_id,
                    "prompt": [{"type": "text", "text": "1"}],
                },
            )
            await _drain_bind_preamble(client)

            # Now publish a notification on target_a's bus. Its
            # session_id is target_a.session_id; the client should
            # receive it keyed to control_id.
            target_a.publish(
                session_notification(
                    target_a.session_id,
                    update_agent_message(text_block("hello from target-a")),
                )
            )
            notif = await client.next_notification()
            assert notif["method"] == "session/update"
            # Wire id (control_id), NOT target_a.session_id.
            assert notif["params"]["sessionId"] == control_id
            assert notif["params"]["sessionId"] != target_a.session_id
            assert notif["params"]["update"]["content"]["text"] == "hello from target-a"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# P2 regression: rebinding stops old forwarders
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_rebind_stops_old_forwarders_and_detaches_subscriber(
    short_data_dir: Path, register_target
) -> None:
    """Calling session/load a second time tears down the prior target's forwarder.

    Without this, the old subscriber stream stays attached to the
    old target's pub/sub bus AND the old forwarder task keeps
    pumping its notifications into the same connection — clients
    would see cross-stream pollution from two targets and the old
    target would leak a subscriber slot forever.
    """
    target_a, _tr_a = _make_live_session_with_transcript()
    target_b, _tr_b = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(
            task="task-a", sample_id="s-a", epoch=0, acp_session=target_a
        ),
        _make_active_sample(
            task="task-b", sample_id="s-b", epoch=0, acp_session=target_b
        ),
    )
    async with acp_server(eval_id="evt-rebind", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            # First bind: target A.
            await client.request(
                "session/load",
                {
                    "cwd": "/tmp",
                    "mcpServers": [],
                    "sessionId": target_a.session_id,
                },
            )
            await _drain_bind_preamble(client)
            # target_a has 1 subscriber (this connection); target_b has 0.
            assert len(target_a._subscribers) == 1
            assert len(target_b._subscribers) == 0

            # Rebind to target B via session/load.
            await client.request(
                "session/load",
                {
                    "cwd": "/tmp",
                    "mcpServers": [],
                    "sessionId": target_b.session_id,
                },
            )
            await _drain_bind_preamble(client)
            # Old target was cleanly detached; new target has the subscriber.
            assert len(target_a._subscribers) == 0, (
                "rebinding leaked the old target's subscriber"
            )
            assert len(target_b._subscribers) == 1

            # And publishing on the OLD target reaches no one (no
            # cross-stream pollution into this connection).
            target_a.publish(
                session_notification(
                    target_a.session_id,
                    update_agent_message(text_block("ghost from A")),
                )
            )
            target_b.publish(
                session_notification(
                    target_b.session_id,
                    update_agent_message(text_block("real from B")),
                )
            )
            notif = await client.next_notification()
            assert notif["params"]["update"]["content"]["text"] == "real from B"
            # No second notification (target_a's publish went nowhere).
            await asyncio.sleep(0.05)
            assert not client.notification_pending()
        finally:
            await client.close()
