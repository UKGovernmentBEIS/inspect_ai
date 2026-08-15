"""End-to-end ACP elicitation flow over a real AF_UNIX socket.

Mirrors the approval E2E block at the bottom of
``tests/agent/test_acp/test_approval.py``. The test:

1. Stubs an :class:`ActiveSample` with a live
   :class:`~inspect_ai.agent._acp.transport_live.LiveAcpTransport`.
2. Spins up an ``acp_server`` bound to an AF_UNIX socket.
3. Connects a hand-rolled JSON-RPC client that advertises
   ``elicitation.form`` capability and answers ``elicitation/create``
   requests with a configurable response.
4. Drives :func:`inspect_ai.util._input.acp.acp_handler` from the "agent
   side" and asserts the wire payload + the response → InputResult
   round-trip.

Three variants cover the three response actions (accept / decline /
cancel). Each is parameterized via a separate test so failures point
straight at the broken action mapping.
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
from acp.schema import (
    ElicitationSchema,
    ElicitationStringPropertySchema,
)
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.util import InputRequest
from inspect_ai.util._input.acp import acp_handler

# Heavy socket-integration suite: real AF_UNIX round-trips + agent evals
# (~1.3s+ per test). Marked slow to keep it off the per-PR CI critical path
# (the slow suite runs in a separate environment); lighter ACP tests still run
# on every PR.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


@pytest.fixture
def short_data_dir(monkeypatch):
    """Short /tmp data dir so AF_UNIX paths fit in 104 chars on macOS."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_elic_", dir="/tmp"))

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


class _ElicitationClientRpcStub:
    """JSON-RPC client that answers ``elicitation/create`` with a fixed response.

    Lifted from ``_ClientRpcStub`` in ``test_approval.py`` and adapted
    to dispatch on ``elicitation/create`` instead of
    ``session/request_permission``. We don't share the helper because
    Phase 6b will likely subsume both into a generic harness when the
    inline-card primitive lands; until then keeping them independent
    keeps the diff small.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        elicitation_response: dict[str, Any],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._elicitation_response = elicitation_response
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.received_elicitation_request: dict[str, Any] | None = None
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
                if (
                    "method" in msg
                    and msg["method"] == "elicitation/create"
                    and "id" in msg
                ):
                    self.received_elicitation_request = msg
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "result": self._elicitation_response,
                    }
                    self._writer.write((json.dumps(response) + "\n").encode("utf-8"))
                    await self._writer.drain()
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(msg["id"], None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
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


def _trivial_schema() -> ElicitationSchema:
    return ElicitationSchema(
        properties={
            "answer": ElicitationStringPropertySchema(type="string", title="Answer")
        },
        required=["answer"],
    )


# ---------------------------------------------------------------------------
# E2E round-trip — one test per response action
# ---------------------------------------------------------------------------


async def _drive_e2e_round_trip(
    *,
    short_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    elicitation_response: dict[str, Any],
) -> tuple[Any, dict[str, Any] | None]:
    """Set up an ACP server, attach an elicitation-capable client, dispatch.

    Returns ``(input_result, received_wire_request)``. Per-test wrapper
    assertions vary; the harness is shared so the three response cases
    only differ in the response dict and the expected mapping.
    """
    session = LiveAcpTransport()
    session._attachable_override = True
    sample = MagicMock()
    sample.acp_transport = session
    sample.task = "t"
    sample.sample.id = "s"
    sample.epoch = 0
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [sample])
    monkeypatch.setattr("inspect_ai.agent._acp.picker.active_samples", lambda: [sample])
    # ``current_acp_transport`` resolves via ``sample_active().acp_transport``
    # when no ContextVar is set, so wire up sample_active to point at us.
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)

    async with acp_server(eval_id="evt-elic", transport=True) as server:
        assert server is not None and server.socket_path is not None
        reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        client = _ElicitationClientRpcStub(
            reader, writer, elicitation_response=elicitation_response
        )
        try:
            # Handshake: initialize + bind by direct loadSession.
            # The elicitation.form capability is what flips the
            # server-side gate so the connection joins the
            # elicitation registry on bind.
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "test", "version": "0"},
                    "clientCapabilities": {"elicitation": {"form": {}}},
                },
            )
            await client.request(
                "session/load",
                {
                    "cwd": "/tmp",
                    "mcpServers": [],
                    "sessionId": session.session_id,
                },
            )
            # Give the event loop one tick to let _start_forwarders /
            # notify_elicitation_attach run.
            await asyncio.sleep(0.05)
            assert session.has_elicitation_clients() is True

            result = await acp_handler(
                InputRequest(
                    message="What's the magic word?",
                    schema=_trivial_schema(),
                )
            )
            return result, client.received_elicitation_request
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_elicitation_over_real_socket_accept_round_trip(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``accept`` response → InputResult(accepted, content)."""
    result, received = await _drive_e2e_round_trip(
        short_data_dir=short_data_dir,
        monkeypatch=monkeypatch,
        elicitation_response={"action": "accept", "content": {"answer": "please"}},
    )
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"answer": "please"}
    # The client captured the wire request. Verify the payload shape
    # the server emits matches the canonical ACP form-session shape.
    assert received is not None
    params = received["params"]
    assert params["message"] == "What's the magic word?"
    assert params["mode"] == "form"
    assert "sessionId" in params
    assert params["requestedSchema"]["properties"]["answer"]["type"] == "string"


@skip_if_trio
@unix_only
async def test_elicitation_over_real_socket_decline_round_trip(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``decline`` response → InputResult(declined, no content)."""
    result, _ = await _drive_e2e_round_trip(
        short_data_dir=short_data_dir,
        monkeypatch=monkeypatch,
        elicitation_response={"action": "decline"},
    )
    assert result is not None
    assert result.outcome == "declined"
    assert result.content is None


@skip_if_trio
@unix_only
async def test_elicitation_over_real_socket_cancel_round_trip(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``cancel`` response → InputResult(cancelled, no content)."""
    result, _ = await _drive_e2e_round_trip(
        short_data_dir=short_data_dir,
        monkeypatch=monkeypatch,
        elicitation_response={"action": "cancel"},
    )
    assert result is not None
    assert result.outcome == "cancelled"
    assert result.content is None


@skip_if_trio
@unix_only
async def test_elicitation_e2e_attach_after_fire(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ask_user`` fires BEFORE any ACP client attaches; result still routes via ACP.

    Pins the exclusive-routing contract: ``--acp-server`` is on, the
    agent calls ``ask_user`` immediately (before the operator runs
    ``inspect acp``), the shim parks on the elicitation registry's
    attach event, the operator attaches, the form submits, and the
    answer reaches the agent — without the in-proc panel / console
    ever being touched. Inverse timing of the normal E2E tests
    above; this is the scenario the notification-driven workflow
    actually depends on.
    """
    session = LiveAcpTransport()
    session._attachable_override = True
    sample = MagicMock()
    sample.acp_transport = session
    sample.task = "t"
    sample.sample.id = "s"
    sample.epoch = 0
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [sample])
    monkeypatch.setattr("inspect_ai.agent._acp.picker.active_samples", lambda: [sample])
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)

    async with acp_server(eval_id="evt-elic-aaf", transport=True) as server:
        assert server is not None and server.socket_path is not None

        # FIRE acp_handler before any client attaches; the shim parks
        # on subscribe_elicitation_attach.
        shim_task = asyncio.create_task(
            acp_handler(
                InputRequest(
                    message="What's the secret word?",
                    schema=_trivial_schema(),
                )
            )
        )
        await asyncio.sleep(0.05)
        assert not shim_task.done()  # parked, no fallback to panel/console
        assert session.has_elicitation_clients() is False  # really nobody yet

        # NOW attach an elicitation-capable client.
        reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        client = _ElicitationClientRpcStub(
            reader,
            writer,
            elicitation_response={
                "action": "accept",
                "content": {"answer": "shibboleth"},
            },
        )
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "test", "version": "0"},
                    "clientCapabilities": {"elicitation": {"form": {}}},
                },
            )
            await client.request(
                "session/load",
                {
                    "cwd": "/tmp",
                    "mcpServers": [],
                    "sessionId": session.session_id,
                },
            )
            # The bind sequence fires notify_elicitation_attach, which
            # wakes the parked shim; the shim then dispatches the
            # outbound elicitation/create request that our stub answers.
            result = await asyncio.wait_for(shim_task, timeout=5.0)
            assert result is not None
            assert result.outcome == "accepted"
            assert result.content == {"answer": "shibboleth"}
            assert client.received_elicitation_request is not None
        finally:
            await client.close()
