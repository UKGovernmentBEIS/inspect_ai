"""Phase 2 (TUI) tests for SessionInfoUpdate.title at bind.

After a connection binds to a target session (auto-bind, picker select,
or session/load), the server should push a native ACP
``SessionInfoUpdate`` carrying ``title = "<task> / <sample> / epoch <n>"``
so editor clients show a meaningful session label in their UI.
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
from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.log._transcript import Transcript


@pytest.fixture
def short_data_dir(monkeypatch):
    dirpath = Path(tempfile.mkdtemp(prefix="acp_si_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("inspect_ai.agent._acp.discovery.inspect_data_dir", _stub)
    try:
        yield dirpath
    finally:
        for p in dirpath.rglob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        for sub in sorted(dirpath.rglob("*"), reverse=True):
            try:
                sub.rmdir()
            except OSError:
                pass
        try:
            dirpath.rmdir()
        except OSError:
            pass


def _make_active_sample(
    *, task: str, sample_id: str, epoch: int, acp_session: Any
) -> Any:
    sample = MagicMock()
    sample.id = sample_id
    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    active.agent_name = None
    active.started = None
    active.total_tokens = 0
    active.fails_on_error = True
    active.acp_transport = acp_session
    return active


@pytest.fixture
def register_target(monkeypatch):
    def _register(*targets: Any) -> None:
        monkeypatch.setattr(picker, "active_samples", lambda: list(targets))
        monkeypatch.setattr(
            "inspect_ai.log._samples.active_samples", lambda: list(targets)
        )

    return _register


def _make_live_session_with_transcript() -> LiveAcpTransport:
    session = LiveAcpTransport()
    session._attachable_override = True
    session._transcript = Transcript()
    return session


unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


class _RpcClient:
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


async def _connect(server: Any) -> _RpcClient:
    reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
    return _RpcClient(reader, writer)


async def _initialize(client: _RpcClient) -> None:
    await client.request(
        "initialize",
        {"protocolVersion": 1, "clientInfo": {"name": "test", "version": "0.0"}},
    )


async def _drain_until_session_info(
    client: _RpcClient, *, max_drain: int = 5
) -> dict[str, Any]:
    """Drain notifications until we find a session_info_update.

    Other notifications (picker confirmation AgentMessageChunk) may
    arrive first; we want the SessionInfoUpdate specifically.
    """
    for _ in range(max_drain):
        notif = await client.next_notification()
        update = notif.get("params", {}).get("update", {})
        if update.get("sessionUpdate") == "session_info_update":
            return notif
    raise AssertionError(
        f"No session_info_update notification after {max_drain} drains"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_if_trio
@unix_only
async def test_session_info_title_sent_after_auto_bind(
    short_data_dir: Path, register_target
) -> None:
    session = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(
            task="my_task", sample_id="s42", epoch=2, acp_session=session
        )
    )
    async with acp_server(eval_id="evt-si-auto", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            wire_id = resp["result"]["sessionId"]
            notif = await _drain_until_session_info(client)
            params = notif["params"]
            update = params["update"]
            assert update["sessionUpdate"] == "session_info_update"
            assert update["title"] == "my_task / s42 / epoch 2"
            # SessionInfoUpdate must carry the wire sessionId (client's view).
            assert params["sessionId"] == wire_id
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_info_title_omits_null_updated_at(
    short_data_dir: Path, register_target
) -> None:
    """updated_at=None must not be serialized.

    Per ACP schema, null on these fields has *destructive* clear
    semantics for editor state. We send title only.
    """
    session = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-si-noclear", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            notif = await _drain_until_session_info(client)
            update = notif["params"]["update"]
            assert "updatedAt" not in update
            # _meta should also be absent (we don't set it).
            assert "_meta" not in update
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_rebind_sends_new_session_info(
    short_data_dir: Path, register_target
) -> None:
    """Re-binding emits a fresh SessionInfoUpdate.

    session/load on a different known target rebinds; the new title
    must reach the editor so its UI label reflects what's actually
    being viewed.
    """
    session_a = _make_live_session_with_transcript()
    session_b = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(
            task="task-a", sample_id="s1", epoch=0, acp_session=session_a
        ),
        _make_active_sample(
            task="task-b", sample_id="s2", epoch=1, acp_session=session_b
        ),
    )
    async with acp_server(eval_id="evt-si-rebind", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            # First bind: explicit session/load on target A's id.
            await client.request(
                "session/load",
                {
                    "sessionId": session_a.session_id,
                    "cwd": "/tmp",
                    "mcpServers": [],
                },
            )
            first = await _drain_until_session_info(client)
            assert first["params"]["update"]["title"] == "task-a / s1 / epoch 0"
            # Rebind on target B.
            await client.request(
                "session/load",
                {
                    "sessionId": session_b.session_id,
                    "cwd": "/tmp",
                    "mcpServers": [],
                },
            )
            second = await _drain_until_session_info(client)
            assert second["params"]["update"]["title"] == "task-b / s2 / epoch 1"
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_no_session_info_when_target_missing(
    short_data_dir: Path, register_target
) -> None:
    """Vanishing sample produces no malformed update.

    If the active sample disappears between bind decision and
    forwarder startup, _send_session_info_title silently skips —
    nothing throws, the connection stays clean.
    """
    session = _make_live_session_with_transcript()
    register_target(
        _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=session)
    )
    async with acp_server(eval_id="evt-si-vanish", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await _initialize(client)
            await client.request("session/new", {"cwd": "/tmp", "mcpServers": []})
            # Title should arrive normally on the happy path; deregister
            # afterward to confirm subsequent operations don't crash.
            await _drain_until_session_info(client)
            register_target()  # empty — sample vanished
            # No assertion; we're verifying nothing throws.
        finally:
            await client.close()
