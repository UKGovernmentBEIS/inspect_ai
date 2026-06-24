"""End-to-end smoke test for a generic ACP client (no Inspect extensions).

Pins the contract that the server is fully usable by an ACP-conformant
client that knows nothing about ``inspect/*`` methods, the ``inspect.*``
``_meta`` namespace, or Inspect's plan-rendering / raw-events opt-ins.

The Inspect TUI uses ``inspect/list_sessions`` for multi-eval
aggregation, so the standard ``session/new`` picker path is otherwise
only exercised by lower-level unit tests in ``test_server_dispatch.py``
+ ``test_server_forwarding.py``. This file is the regression guard for
the full Zed-equivalent flow.

The asserts deliberately do NOT touch ``inspect.*`` keys — they read
the picker from the TEXT body, address the bound session by the wire
``sessionId`` from the response, and consume ``session/update``
notifications via the standard ACP discriminators only.

If a future change to the server breaks generic-client compatibility,
this test should fail before any Inspect-aware client notices.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.helpers import session_notification, text_block, update_agent_message
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp import picker
from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.log._transcript import Transcript

# Heavy socket-integration suite: real AF_UNIX round-trips + agent evals
# (~1.3s+ per test). Marked slow to keep it off the per-PR CI critical path
# (the slow suite runs in a separate environment); lighter ACP tests still run
# on every PR.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Fixtures (mirror the patterns used in test_server_dispatch / forwarding)
# ---------------------------------------------------------------------------


@pytest.fixture
def short_data_dir(monkeypatch):
    """Short /tmp data directory so AF_UNIX paths fit in 104 chars (macOS)."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_std_", dir="/tmp"))

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


def _make_active_sample(
    *, task: str, sample_id: str, epoch: int, acp_session: Any
) -> Any:
    sample = MagicMock()
    sample.id = sample_id
    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    # Explicit None / 0 so MagicMock doesn't auto-wrap and break JSON
    # serialization in the picker payload.
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
            "inspect_ai.log._samples.active_samples",
            lambda: list(targets),
        )

    return _register


def _make_live_session_with_transcript() -> LiveAcpTransport:
    """LiveAcpTransport with a real Transcript wired up, bypassing __aenter__."""
    session = LiveAcpTransport()
    session._attachable_override = True
    session._transcript = Transcript()
    return session


# ---------------------------------------------------------------------------
# Minimal line-oriented JSON-RPC client (test-only)
# ---------------------------------------------------------------------------


class _RpcClient:
    """Bare-bones JSON-RPC 2.0 client over a stream pair.

    Identical in shape to the helpers used by the dispatch / forwarding
    suites but kept local to this file so the test stays self-contained
    and the assertions clearly read as "what a generic client does."
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


# ---------------------------------------------------------------------------
# The smoke test
# ---------------------------------------------------------------------------


_PICKER_INDEX_RE = re.compile(r"^\s*(\d+)\.\s", re.MULTILINE)
"""Picker text body lines look like ``  1. task / sample s1 / epoch 0   [uuid]``.

A generic ACP client parses the text to enumerate selectable indices —
it has no knowledge of ``inspect.picker.targets`` ``_meta``.
"""


def _assert_no_inspect_meta(payload: Any, *, path: str = "$") -> None:
    """Recursively assert no ``inspect.*`` key is present in a payload.

    The contract: a standard ACP client can ignore ``_meta`` entirely
    and still get a complete picture from the structured fields. Used
    here only to confirm the server isn't accidentally LEAKING
    inspect-namespaced semantics into a place where the standard
    fields don't already convey the same info.

    Tightening over time: if we add a new ``inspect.*`` meta key, the
    test will catch it and force a conscious decision about whether
    that key duplicates info already in the standard fields.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(k, str) and (
                k.startswith("inspect.") or k.startswith("inspect/")
            ):
                # Allowlist: the picker notification carries
                # `inspect.picker.targets` as a structured mirror of
                # the text-body picker list — that's the *intended*
                # enrichment for capability-aware clients, and a
                # generic client just ignores it. We're not testing
                # that the server avoids the key entirely; we're
                # testing that a client can succeed without reading it.
                if k == "inspect.picker.targets":
                    continue
                # Per-chunk model attribution + generation lifecycle
                # markers ride on assistant chunks; standard clients
                # ignore them without losing the ability to render
                # the chunk text and infer activity from arrival.
                if k in {
                    "inspect.model",
                    "inspect.model_event_uuid",
                    "inspect.model_event_pending",
                    "inspect.model_event_complete",
                    "inspect.message_id",
                    "inspect.message_role",
                    "inspect.user_source",
                    # Binding-confirmation interactivity flag. A generic
                    # client reads the "Observing" / "Bound to" text body
                    # instead; the flag just lets Inspect-aware clients
                    # gate their composer without parsing prose.
                    "inspect.interactive",
                }:
                    continue
                pytest.fail(
                    f"unexpected inspect-namespaced key {k!r} at {path} "
                    f"(value={v!r}). If this is a NEW extension, add it to "
                    f"the allowlist in this test and update inspect_ext.py + "
                    f"the design doc's Standard ACP compatibility table."
                )
            _assert_no_inspect_meta(v, path=f"{path}.{k}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _assert_no_inspect_meta(item, path=f"{path}[{i}]")


@skip_if_trio
@unix_only
async def test_generic_acp_client_full_picker_flow(
    short_data_dir: Path, register_target
) -> None:
    """A non-Inspect ACP client can drive the server end-to-end.

    The flow exercised:

    1. ``initialize`` with a generic ``clientInfo`` and no ``_meta``
       capabilities. Confirms the response advertises standard agent
       capabilities and that the server isn't gating on
       ``inspect.*`` opt-ins.
    2. ``session/new`` with two targets registered → response carries a
       control ``sessionId`` and the picker is pushed as a standard
       ``session/update`` whose body is a parseable ``agent_message_chunk``.
    3. The client parses the picker TEXT BODY (not ``_meta``) to find a
       selectable index.
    4. ``session/prompt`` with the index text → server rebinds and
       confirms via another standard ``session/update``. The wire
       ``sessionId`` is preserved across the rebind per ACP convention.
    5. A real ``session/prompt`` reaches the bound target's
       ``submit_user_message``.
    6. A ``session/cancel`` notification reaches the bound target's
       ``cancel_current_turn``.
    7. A ``session.publish(...)`` on the bound target reaches the client
       as a standard ``session/update`` with a recognizable
       ``agent_message_chunk``.

    No call in this test uses an ``inspect/*`` method. The recursive
    ``_meta`` audit (:func:`_assert_no_inspect_meta`) catches new
    inspect-namespaced fields landing in places that would surprise
    a generic client.
    """
    # Two live sessions, both backed by real LiveAcpTransport + transcript
    # so the bus + forwarder path works end-to-end (not stubbed).
    live_a = _make_live_session_with_transcript()
    live_b = _make_live_session_with_transcript()
    # Spy on the producer-side methods the server forwards to.
    submit_calls_a: list[Any] = []
    submit_calls_b: list[Any] = []
    cancel_calls_a: list[None] = []
    cancel_calls_b: list[None] = []
    live_a.submit_user_message = lambda msg: submit_calls_a.append(msg)  # type: ignore[method-assign]
    live_b.submit_user_message = lambda msg: submit_calls_b.append(msg)  # type: ignore[method-assign]
    live_a.cancel_current_turn = lambda cause="user_cancel": cancel_calls_a.append(None)  # type: ignore[method-assign]
    live_b.cancel_current_turn = lambda cause="user_cancel": cancel_calls_b.append(None)  # type: ignore[method-assign]

    sample_a = _make_active_sample(
        task="task_alpha", sample_id="s1", epoch=0, acp_session=live_a
    )
    sample_b = _make_active_sample(
        task="task_beta", sample_id="s2", epoch=1, acp_session=live_b
    )
    register_target(sample_a, sample_b)

    async with acp_server(eval_id="evt-std-client", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            # ----- Step 1: initialize (no inspect capabilities) -------
            init_resp = await client.request(
                "initialize",
                {
                    # Generic client identity — NOT in PLAN_RENDERING_CLIENTS,
                    # NOT opting into inspect.raw_events.
                    "protocolVersion": 1,
                    "clientInfo": {"name": "generic-acp-test", "version": "0.0"},
                    "clientCapabilities": {},
                },
            )
            assert "result" in init_resp, init_resp
            init_result = init_resp["result"]
            assert "agentCapabilities" in init_result
            _assert_no_inspect_meta(init_result, path="initialize.result")

            # ----- Step 2: session/new with two targets -> picker -----
            new_resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            assert "result" in new_resp, new_resp
            wire_session_id = new_resp["result"]["sessionId"]
            assert isinstance(wire_session_id, str) and wire_session_id

            picker_notif = await client.next_notification()
            assert picker_notif["method"] == "session/update"
            params = picker_notif["params"]
            assert params["sessionId"] == wire_session_id
            update = params["update"]
            assert update["sessionUpdate"] == "agent_message_chunk"
            picker_text = update["content"]["text"]
            assert "task_alpha" in picker_text and "task_beta" in picker_text
            # A generic client extracts selectable indices by parsing
            # the line-prefix numbers. Two targets → two indices.
            indices = _PICKER_INDEX_RE.findall(picker_text)
            assert indices == ["1", "2"], (
                f"picker text should expose '1.' and '2.' line prefixes; "
                f"got {indices!r} in {picker_text!r}"
            )

            # ----- Step 3: pick second target via text-body index -----
            select_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": wire_session_id,
                    "prompt": [{"type": "text", "text": "2"}],
                },
            )
            assert select_resp["result"]["stopReason"] == "end_turn"

            # Bind confirmation arrives as a standard session/update
            # on the SAME wire sessionId (stable across rebind per ACP).
            confirm = await client.next_notification()
            assert confirm["method"] == "session/update"
            assert confirm["params"]["sessionId"] == wire_session_id
            assert confirm["params"]["update"]["sessionUpdate"] == "agent_message_chunk"
            assert "Bound to" in confirm["params"]["update"]["content"]["text"]

            # The post-bind SessionInfoUpdate (title) also rides the
            # standard channel. Drain it before doing more interactive
            # work so subsequent notifications aren't ordered behind it.
            title_notif = await client.next_notification()
            assert title_notif["method"] == "session/update"
            assert (
                title_notif["params"]["update"]["sessionUpdate"]
                == "session_info_update"
            )

            # ----- Step 4: real prompt forwards to submit_user_message -
            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": wire_session_id,
                    "prompt": [{"type": "text", "text": "hello agent"}],
                },
            )
            assert prompt_resp["result"]["stopReason"] == "end_turn"
            assert submit_calls_a == [], "selected sample_b, not sample_a"
            assert len(submit_calls_b) == 1
            assert submit_calls_b[0].content == "hello agent"
            # Server tags ACP-injected user messages as operator.
            assert submit_calls_b[0].source == "operator"

            # ----- Step 5: cancel notification reaches cancel_current_turn
            await client.notify("session/cancel", {"sessionId": wire_session_id})
            await asyncio.sleep(0.05)
            assert cancel_calls_a == [], "selected sample_b, not sample_a"
            assert len(cancel_calls_b) == 1

            # ----- Step 6: agent publish reaches client as session/update
            live_b.publish(
                session_notification(
                    wire_session_id,
                    update_agent_message(text_block("hi from agent")),
                )
            )
            agent_notif = await client.next_notification()
            assert agent_notif["method"] == "session/update"
            assert agent_notif["params"]["sessionId"] == wire_session_id
            agent_update = agent_notif["params"]["update"]
            assert agent_update["sessionUpdate"] == "agent_message_chunk"
            assert agent_update["content"]["text"] == "hi from agent"

            # ----- Step 7: meta audit across everything we received ---
            # Picker notif carries inspect.picker.targets by design
            # (allowlisted); the agent chunks may carry inspect.model
            # and friends (also allowlisted). Anything ELSE is a new
            # extension that needs a conscious decision.
            for received in (
                init_result,
                params,
                confirm["params"],
                title_notif["params"],
                agent_notif["params"],
            ):
                _assert_no_inspect_meta(received)
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_generic_client_sees_clean_error_when_bound_session_ends(
    short_data_dir: Path, register_target
) -> None:
    """Pin the standard-ACP fallback for ``inspect/session_ended``.

    The server pushes ``inspect/session_ended`` to Inspect-aware
    clients when the bound react loop exits mid-eval. Non-Inspect
    clients don't know that method — they discover the dead session
    on their next ``session/prompt``, which must return a clean
    ``internal_error`` with a structured payload they can surface
    in their UI.

    See the design doc's "Standard ACP compatibility" section for
    the rationale (no standard server→client session-end notification
    exists in ACP today).
    """
    live = _make_live_session_with_transcript()
    sample = _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=live)
    register_target(sample)

    async with acp_server(eval_id="evt-std-ended", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "generic-acp-test", "version": "0.0"},
                    "clientCapabilities": {},
                },
            )
            new_resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            wire_session_id = new_resp["result"]["sessionId"]
            # Single target — server auto-bound; drain the binding
            # confirmation + the post-bind title.
            await client.next_notification()
            await client.next_notification()

            # Simulate the react loop exiting: deregister the sample
            # so _find_live_session returns None. The standard client
            # has no way to know this happened (it'd be the
            # inspect/session_ended notification on an Inspect-aware
            # client) until it tries to interact.
            register_target()  # empty target list

            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": wire_session_id,
                    "prompt": [{"type": "text", "text": "anyone home?"}],
                },
            )
            assert "error" in prompt_resp, prompt_resp
            error = prompt_resp["error"]
            # Structured payload carries a human-readable reason and
            # the target session id — enough for a generic client to
            # surface a clear "session ended" notice.
            assert "data" in error
            assert error["data"].get("reason") == "bound session no longer active"
            assert error["data"].get("target_session_id") == wire_session_id
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_prompt_rejected_when_target_not_attachable(
    short_data_dir: Path, register_target
) -> None:
    """A bound client whose target loses its channel gets a clean error.

    Post-react or between consecutive reacts the transport remains
    registered on the sample, but ``_ref`` is None until the next
    ``maybe_bind``. The connection layer surfaces this so the client
    can drop the binding instead of getting a silently-dropped message.

    Regression for the gap that ``is_attachable`` was introduced to close:
    pre-fix, ``submit_user_message`` no-op'd when ``_ref is None`` and the
    wire call returned a success that didn't land. Connection-layer gate
    surfaces this as a structured error so the client can drop the
    binding instead of getting ghost-success responses.
    """
    live = _make_live_session_with_transcript()
    sample = _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=live)
    register_target(sample)

    async with acp_server(eval_id="evt-unbound", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "generic-acp-test", "version": "0.0"},
                    "clientCapabilities": {},
                },
            )
            new_resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            wire_session_id = new_resp["result"]["sessionId"]
            await client.next_notification()
            await client.next_notification()

            # Simulate react() unbinding: target still on the sample
            # (transport hasn't finalized — scoring window or between
            # consecutive react() invocations), but no channel ref is
            # currently bound, so ``is_attachable`` flips False.
            live._attachable_override = False

            prompt_resp = await client.request(
                "session/prompt",
                {
                    "sessionId": wire_session_id,
                    "prompt": [{"type": "text", "text": "anyone home?"}],
                },
            )
            assert "error" in prompt_resp, prompt_resp
            error = prompt_resp["error"]
            assert "data" in error
            assert error["data"].get("reason") == "session not currently attachable"
            assert error["data"].get("target_session_id") == wire_session_id
        finally:
            await client.close()


@skip_if_trio
@unix_only
async def test_session_cancel_dropped_when_target_not_attachable(
    short_data_dir: Path, register_target
) -> None:
    """A cancel notification for a non-attachable target is silently dropped.

    Notifications can't return errors, so the connection layer drops the
    cancel rather than letting it record a phantom ``InterruptEvent`` or
    flip ``interrupt_pending`` (which would leave the TUI's prompt-mode
    indicator stuck on, since no agent loop will consume the resolution).
    """
    live = _make_live_session_with_transcript()
    cancel_calls: list[None] = []
    # Spy on the producer-side cancel so we can assert it was NOT invoked.
    live.cancel_current_turn = lambda cause="user_cancel": cancel_calls.append(  # type: ignore[method-assign]
        None
    )
    sample = _make_active_sample(task="t", sample_id="s", epoch=0, acp_session=live)
    register_target(sample)

    async with acp_server(eval_id="evt-unbound-cancel", transport=True) as server:
        assert server is not None
        client = await _connect(server)
        try:
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "generic-acp-test", "version": "0.0"},
                    "clientCapabilities": {},
                },
            )
            new_resp = await client.request(
                "session/new", {"cwd": "/tmp", "mcpServers": []}
            )
            wire_session_id = new_resp["result"]["sessionId"]
            await client.next_notification()
            await client.next_notification()

            # Unbind: simulate the post-react / between-react state.
            live._attachable_override = False

            # Send cancel — must be silently dropped.
            await client.notify("session/cancel", {"sessionId": wire_session_id})
            # Give the server a moment to process the notification.
            await asyncio.sleep(0.05)

            assert cancel_calls == [], (
                f"cancel reached transport while not attachable: {cancel_calls}"
            )
        finally:
            await client.close()
