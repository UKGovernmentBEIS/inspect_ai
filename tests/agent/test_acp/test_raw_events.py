"""Phase 10 integration tests for the opt-in raw event stream.

Tests the per-connection raw forwarder that subscribes to the bound
target's transcript and pushes each transcript event out as an
``inspect/event`` JSON-RPC notification when the client signals
``clientCapabilities._meta["inspect.raw_events"]: true`` at
initialize.

Key contracts under test:
- opt-in detection
- supplement-not-replacement (raw + semantic both fire)
- coverage of events the semantic router DROPS
- silent for non-opted clients
- replay-on-attach for raw events
- cleanup unsubscribes from the transcript
- pre-condensation guarantee (subscribers see uncondensed event.call)
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
    text_block,
    update_agent_message,
)
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp import picker
from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.session_live import LiveAcpSession
from inspect_ai.agent._acp.session_router import ELISION_THRESHOLD_BYTES
from inspect_ai.event._compaction import CompactionEvent
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._interrupt import InterruptEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import Transcript
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput

# ---------------------------------------------------------------------------
# Fixtures (reused from forwarding tests but kept self-contained)
# ---------------------------------------------------------------------------


@pytest.fixture
def short_data_dir(monkeypatch):
    dirpath = Path(tempfile.mkdtemp(prefix="acp_raw_", dir="/tmp"))

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


def _make_active_sample(*, acp_session: Any) -> Any:
    sample = MagicMock()
    sample.id = "s1"
    active = MagicMock()
    active.task = "test"
    active.sample = sample
    active.epoch = 0
    # Explicit None on the new fields so MagicMock doesn't auto-wrap
    # them (would otherwise blow up JSON serialization downstream).
    active.agent_name = None
    active.started = None
    active.total_tokens = 0
    active.acp_session = acp_session
    return active


@pytest.fixture
def register_target(monkeypatch):
    def _register(*targets: Any) -> None:
        monkeypatch.setattr(picker, "active_samples", lambda: list(targets))
        monkeypatch.setattr(
            "inspect_ai.log._samples.active_samples",
            lambda: list(targets),
        )

    return _register


class _RpcClient:
    """Line-oriented JSON-RPC 2.0 client (duplicated from forwarding tests)."""

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


def _make_live_session() -> tuple[LiveAcpSession, Transcript]:
    session = LiveAcpSession()
    tr = Transcript()
    session._transcript = tr
    return session, tr


async def _initialize(
    client: _RpcClient, *, raw_events: bool = False, client_name: str = "test"
) -> None:
    params: dict[str, Any] = {
        "protocolVersion": 1,
        "clientInfo": {"name": client_name, "version": "0.0"},
    }
    if raw_events:
        params["clientCapabilities"] = {"_meta": {"inspect.raw_events": True}}
    await client.request("initialize", params)


async def _drain_until(
    client: _RpcClient, method: str, *, timeout: float = 2.0
) -> dict[str, Any] | None:
    """Drain notifications until one matching ``method`` arrives, or timeout."""
    try:
        while True:
            notif = await client.next_notification(timeout=timeout)
            if notif.get("method") == method:
                return notif
    except asyncio.TimeoutError:
        return None


def _model_event(text: str) -> ModelEvent:
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


# ---------------------------------------------------------------------------
# Live raw forwarding
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_raw_events_default_off(short_data_dir: Path, register_target) -> None:
    """Without the opt-in, no inspect/event notifications are emitted."""
    session, tr = _make_live_session()
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-off", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=False)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation
            # Emit a transcript event.
            tr._event(InfoEvent(source="test", data={"hello": "world"}))
            await asyncio.sleep(0.05)
            # No inspect/event notification was sent.
            while client.notification_pending():
                notif = await client.next_notification()
                assert notif["method"] != "inspect/event"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_raw_events_opt_in_emits_inspect_event(
    short_data_dir: Path, register_target
) -> None:
    """With the opt-in, transcript events surface as inspect/event notifications."""
    session, tr = _make_live_session()
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-on", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation
            tr._event(InfoEvent(source="my-source", data={"key": "value"}))
            notif = await _drain_until(client, "inspect/event")
            assert notif is not None
            assert notif["params"]["event"] == "info"
            assert notif["params"]["source"] == "my-source"
            assert notif["params"]["data"] == {"key": "value"}
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_raw_events_supplement_semantic_stream(
    short_data_dir: Path, register_target
) -> None:
    """Both session/update AND inspect/event fire for events the semantic router maps."""
    session, tr = _make_live_session()
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-supplement", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation

            # Trigger a notification through the publish bus (semantic) AND
            # a transcript event (raw). For a single ModelEvent on the
            # transcript, the live router would publish a session/update;
            # since we're bypassing the router (session.__aenter__ wasn't
            # called for testability), publish manually + tr._event in
            # parallel to show both paths reach the client.
            session.publish(
                session_notification(
                    session.session_id,
                    update_agent_message(text_block("semantic")),
                )
            )
            tr._event(InfoEvent(source="raw-only", data={"x": 1}))

            saw_semantic = False
            saw_raw = False
            # Drain a few notifications looking for both.
            try:
                for _ in range(4):
                    notif = await client.next_notification(timeout=0.5)
                    if notif["method"] == "session/update":
                        saw_semantic = True
                    elif notif["method"] == "inspect/event":
                        saw_raw = True
            except asyncio.TimeoutError:
                pass
            assert saw_semantic, "expected at least one session/update"
            assert saw_raw, "expected at least one inspect/event"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_raw_events_cover_router_drops(
    short_data_dir: Path, register_target
) -> None:
    """Events the semantic router drops still surface in the raw stream."""
    session, tr = _make_live_session()
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-drops", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation

            # InterruptEvent is dropped by the semantic router; raw
            # forwarder MUST surface it.
            tr._event(InterruptEvent(source="user_cancel", interrupted="between_turns"))
            notif = await _drain_until(client, "inspect/event")
            assert notif is not None
            assert notif["params"]["event"] == "interrupt"
            assert notif["params"]["source"] == "user_cancel"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_raw_forwarder_unsubscribes_on_disconnect(
    short_data_dir: Path, register_target
) -> None:
    """Disconnecting unregisters the transcript subscriber (no leak)."""
    session, tr = _make_live_session()
    register_target(_make_active_sample(acp_session=session))
    initial_subs = len(tr._additional_subscribers)
    async with acp_server(eval_id="evt-raw-cleanup", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation
            # Subscriber registered while connected.
            assert len(tr._additional_subscribers) == initial_subs + 1
        finally:
            await client.close()
        # After disconnect, subscriber count returns to baseline.
        await asyncio.sleep(0.1)
        assert len(tr._additional_subscribers) == initial_subs


# ---------------------------------------------------------------------------
# Replay-on-attach
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_raw_replay_includes_prior_events(
    short_data_dir: Path, register_target
) -> None:
    """A late raw-opted attach receives prior transcript events as inspect/event."""
    session, tr = _make_live_session()
    tr._event(InfoEvent(source="hist-1", data={"i": 1}))
    tr._event(InfoEvent(source="hist-2", data={"i": 2}))
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-replay", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation
            sources = []
            for _ in range(2):
                notif = await _drain_until(client, "inspect/event")
                assert notif is not None
                sources.append(notif["params"]["source"])
            assert sources == ["hist-1", "hist-2"]
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Pre-condensation + compaction
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_raw_forwarder_sees_uncondensed_model_call(
    short_data_dir: Path, register_target, monkeypatch
) -> None:
    """Subscribers fire BEFORE walk_model_call extracts attachments.

    Verifies raw consumers see ``ModelEvent.call`` with its full inline
    payload, not an attachment-ref version. The transcript's
    ``_process_event`` runs subscribers BEFORE the attachment-extraction
    step (see Phase 10 plan §4a).
    """
    # Force the retention policy to keep model calls so the inline
    # payload isn't zeroed before subscribers fire.
    session, tr = _make_live_session()
    tr._log_model_api = True
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-uncondensed", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation

            # Build a ModelEvent with a non-None call payload large
            # enough that walk_model_call would otherwise hoist it.
            event = _model_event("response")
            event.call = ModelCall(
                request={"big_payload": "x" * 8000}, response={"text": "ok"}
            )
            tr._event(event)
            notif = await _drain_until(client, "inspect/event")
            assert notif is not None
            assert notif["params"]["event"] == "model"
            # call is present and contains the inline request data
            # (NOT an attachment ref).
            assert notif["params"]["call"] is not None
            assert notif["params"]["call"]["request"]["big_payload"].startswith("x")
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_raw_forwarder_surfaces_compaction_event(
    short_data_dir: Path, register_target
) -> None:
    """CompactionEvents appear in the raw stream.

    Compaction emits a fresh CompactionEvent to the transcript without
    mutating prior events — both facts the raw forwarder must
    preserve. The semantic router drops compaction events; the raw
    stream MUST surface them.
    """
    session, tr = _make_live_session()
    # Pre-existing ModelEvent (will be checked for non-mutation).
    pre = _model_event("original-text")
    tr._event(pre)
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-compact", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation

            # Drain the replayed events.
            for _ in range(1):
                await _drain_until(client, "inspect/event")

            # Emit a new CompactionEvent live.
            tr._event(
                CompactionEvent(
                    type="trim",
                    source="inspect",
                    tokens_before=1000,
                    tokens_after=500,
                )
            )
            notif = await _drain_until(client, "inspect/event")
            assert notif is not None
            assert notif["params"]["event"] == "compaction"
            assert notif["params"]["type"] == "trim"

            # Prior ModelEvent is unchanged (still has "original-text").
            assert pre.output.choices[0].message.text == "original-text"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Elision in raw replay
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_raw_replay_elides_oversized_tool_arguments(
    short_data_dir: Path, register_target
) -> None:
    """ToolEvent.arguments larger than the threshold are elided in raw replay."""
    session, tr = _make_live_session()
    big_blob = "x" * (ELISION_THRESHOLD_BYTES + 1000)
    tr._event(
        ToolEvent(
            id="tc-big",
            function="some_tool",
            arguments={"payload": big_blob},
            pending=None,
        )
    )
    register_target(_make_active_sample(acp_session=session))
    async with acp_server(eval_id="evt-raw-elide", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client, raw_events=True)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            await client.next_notification()  # bind confirmation
            notif = await _drain_until(client, "inspect/event")
            assert notif is not None
            assert notif["params"]["event"] == "tool"
            arguments = notif["params"]["arguments"]
            assert arguments.get("_inspect.elided") is True
            assert arguments["_inspect.original_size"] > ELISION_THRESHOLD_BYTES
        finally:
            await client.close()
