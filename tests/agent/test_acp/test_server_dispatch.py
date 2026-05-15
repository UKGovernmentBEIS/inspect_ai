"""Phase 9 integration tests for the picker / dispatch layer of `_AcpServer`.

These tests exercise the full request/response + notification cycle
over a real AF_UNIX loopback socket. They stub `_picker.active_samples`
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

from inspect_ai.agent._acp import _picker
from inspect_ai.agent._acp._picker import PICKER_META_KEY
from inspect_ai.agent._acp._server import acp_server

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
        "inspect_ai.agent._acp._server.inspect_data_dir",
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
) -> Any:
    sample = MagicMock()
    sample.id = sample_id
    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    if session_id is None:
        active.acp_session = None
    else:
        session = MagicMock()
        session.session_id = session_id
        active.acp_session = session
    return active


@pytest.fixture
def stub_targets(monkeypatch):
    """Helper that patches `_picker.active_samples` to a controlled list."""

    def _set(samples: list[Any]) -> None:
        monkeypatch.setattr(_picker, "active_samples", lambda: samples)

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
async def test_bound_mode_prompt_returns_method_not_found(
    short_data_dir: Path, stub_targets
) -> None:
    """After binding (via auto-bind), a second `prompt` returns method_not_found.

    This is the Phase 9 boundary: the binding works, but Phase 10 owns
    forwarding `session/prompt` to the target's `submit_user_message`.
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
            # Auto-bound, so the response sessionId IS the target.
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
            assert prompt_resp["error"]["code"] == -32601  # method not found
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

    monkeypatch.setattr(_picker, "active_samples", _changing_active_samples)

    async with acp_server(eval_id="evt-snap-reorder", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            control_id = resp["result"]["sessionId"]
            picker = await client.next_notification()
            shown = [t["sessionId"] for t in picker["params"]["_meta"][PICKER_META_KEY]]
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

    monkeypatch.setattr(_picker, "active_samples", _changing_active_samples)

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
