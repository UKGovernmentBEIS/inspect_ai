"""Tests for the Phase 14 ACP-routed human approver.

Covers:
- option-list construction from configured choices
- response → ``Approval`` round-trip (selected / cancelled / unknown)
- race semantics with stubbed clients (first-wins, exception tolerance,
  all-raise → None, zero-clients → None)
- end-to-end over a real socket (single-client + dual-client race)

The shim is at ``src/inspect_ai/approval/_human/acp.py``; the
session-side registry is exercised separately in
``test_session.py`` (Phase 14 section).
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
    AllowedOutcome,
    DeniedOutcome,
    RequestPermissionRequest,
    RequestPermissionResponse,
    ToolCallUpdate,
)
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.server import acp_server
from inspect_ai.agent._acp.session_live import LiveAcpSession
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human.acp import (
    _approval_from_response,
    _options_from_choices,
    _race_first_response,
    request_human_approval_via_acp,
)
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_call(
    function: str = "bash", arguments: dict[str, Any] | None = None
) -> ToolCall:
    return ToolCall(
        id="tc1",
        function=function,
        arguments=arguments or {"command": "ls -la"},
    )


def _make_view(
    title: str = "bash", content: str = "```bash\nls -la\n```\n"
) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(title=title, format="markdown", content=content)
    )


def _selected(option_id: str) -> RequestPermissionResponse:
    return RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id=option_id)
    )


def _cancelled() -> RequestPermissionResponse:
    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


class _StubClient:
    """An ApproverClient that returns a pre-set response (or raises)."""

    def __init__(
        self,
        response: RequestPermissionResponse | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.response = response
        self.exc = exc
        self.delay = delay
        self.received: list[RequestPermissionRequest] = []
        self.cancelled = False

    async def request_permission(
        self, request: RequestPermissionRequest
    ) -> RequestPermissionResponse:
        self.received.append(request)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.exc is not None:
                raise self.exc
            assert self.response is not None
            return self.response
        except asyncio.CancelledError:
            self.cancelled = True
            raise


# ---------------------------------------------------------------------------
# _options_from_choices
# ---------------------------------------------------------------------------


def test_options_from_choices_two() -> None:
    """Approve + reject → two options with semantic kinds + decision-string optionIds."""
    options = _options_from_choices(["approve", "reject"])
    assert [o.option_id for o in options] == ["approve", "reject"]
    assert [o.kind for o in options] == ["allow_once", "reject_once"]
    assert [o.name for o in options] == ["Approve", "Reject"]


def test_options_from_choices_three_includes_terminate_as_reject_always() -> None:
    """Terminate is the semantic neighbor of ACP's strongest reject."""
    options = _options_from_choices(["approve", "reject", "terminate"])
    assert [o.option_id for o in options] == ["approve", "reject", "terminate"]
    assert options[2].kind == "reject_always"


def test_options_from_choices_includes_escalate_and_modify_as_best_effort() -> None:
    """Unmappable Inspect choices still round-trip via optionId.

    ACP has no first-class kind for modify/escalate — they map to
    semantic neighbors (allow_once / reject_once). The optionId
    round-trip is what actually preserves the decision; kind is
    just a visual hint to the client.
    """
    options = _options_from_choices(["approve", "modify", "reject", "escalate"])
    assert [o.option_id for o in options] == [
        "approve",
        "modify",
        "reject",
        "escalate",
    ]
    assert options[1].kind == "allow_once"  # modify ≈ allow
    assert options[3].kind == "reject_once"  # escalate ≈ reject


# ---------------------------------------------------------------------------
# _approval_from_response
# ---------------------------------------------------------------------------


def test_approval_from_response_selected_known_option() -> None:
    """A recognized optionId maps directly to the matching ApprovalDecision."""
    choices: list[ApprovalDecision] = ["approve", "reject"]
    approval = _approval_from_response(_selected("approve"), choices)
    assert approval.decision == "approve"
    assert approval.explanation is None


def test_approval_from_response_cancelled_becomes_reject() -> None:
    """outcome=cancelled → reject with an explanation noting the cancel."""
    choices: list[ApprovalDecision] = ["approve", "reject"]
    approval = _approval_from_response(_cancelled(), choices)
    assert approval.decision == "reject"
    assert approval.explanation is not None
    assert "cancelled" in approval.explanation.lower()


def test_approval_from_response_unknown_option_becomes_reject() -> None:
    """An optionId outside the configured choices → reject with explanation.

    Pinned because a misbehaving client could synthesize options not
    advertised in the request; we don't want to crash or silently
    misinterpret as a known decision.
    """
    choices: list[ApprovalDecision] = ["approve", "reject"]
    approval = _approval_from_response(_selected("definitely-not-real"), choices)
    assert approval.decision == "reject"
    assert approval.explanation is not None
    assert "unknown" in approval.explanation.lower()
    assert "definitely-not-real" in approval.explanation


# ---------------------------------------------------------------------------
# _race_first_response — multi-client semantics
# ---------------------------------------------------------------------------


def _trivial_request() -> RequestPermissionRequest:
    return RequestPermissionRequest(
        session_id="sess-1",
        tool_call=ToolCallUpdate(tool_call_id="tc1", title="bash ls"),
        options=_options_from_choices(["approve", "reject"]),
    )


@skip_if_trio
async def test_race_first_responder_wins_and_returns_immediately() -> None:
    """Two clients race; first wins; race returns without waiting for slow client.

    Note we do NOT assert the slow client's local task was cancelled
    — ACP has no protocol-level cancel for outbound requests, so we
    deliberately drain losers in the background rather than
    cancelling. The slow client's eventual response is discarded;
    its editor (in reality) keeps showing the stale permission card
    until disconnect. The race orchestrator's contract is just
    "return the first winning response immediately."
    """
    fast = _StubClient(response=_selected("approve"), delay=0.0)
    slow = _StubClient(response=_selected("reject"), delay=1.0)
    choices: list[ApprovalDecision] = ["approve", "reject"]

    # Should return promptly — well before the slow client's 1s delay.
    result = await asyncio.wait_for(
        _race_first_response([fast, slow], _trivial_request(), choices),
        timeout=0.5,
    )
    assert result is not None
    assert result.decision == "approve"
    # Slow client did receive the request (race broadcast to all).
    assert len(slow.received) == 1


@skip_if_trio
async def test_race_cancellation_drains_in_flight_per_client_tasks() -> None:
    """When the race itself is cancelled, per-client tasks aren't orphaned.

    Pinned because the per-client request tasks are spawned with
    ``asyncio.create_task`` — they're INDEPENDENT of the awaiting
    race task. If the race coroutine is cancelled mid-wait without
    cleanup, those tasks survive without an owner and either fire
    "unhandled task exception" if they later raise, or linger
    forever if the client never responds. The race's ``finally``
    block hands survivors to a background drain that awaits and
    discards them — so the per-client tasks ARE still alive but
    they have an owner (the drain task) that will await them when
    they finish.

    Test strategy: simulate a real cancellation, then verify (a)
    the per-client tasks raising LATE doesn't fire an unhandled
    task exception, and (b) the drain tasks complete cleanly when
    their wrapped client task does.
    """
    # Capture any unhandled exceptions that the loop would normally
    # log. The drain's whole job is to prevent these.
    unhandled: list[dict[str, Any]] = []
    loop = asyncio.get_event_loop()
    prev_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda lp, ctx: unhandled.append(ctx))

    try:
        # Slow clients that will eventually RAISE, exercising the
        # "unhandled task exception" risk specifically.
        a = _StubClient(exc=RuntimeError("a failed"), delay=0.1)
        b = _StubClient(exc=RuntimeError("b failed"), delay=0.1)
        choices: list[ApprovalDecision] = ["approve", "reject"]

        race_task = asyncio.create_task(
            _race_first_response([a, b], _trivial_request(), choices)
        )
        # Let the race actually enter asyncio.wait.
        await asyncio.sleep(0.01)
        assert len(a.received) == 1
        assert len(b.received) == 1

        # Cancel the race mid-wait — the caller would do this if the
        # sample is cancelled while the approval is pending.
        race_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await race_task

        # Wait long enough for the slow clients' raises to land and
        # the drain tasks to consume them.
        await asyncio.sleep(0.2)

        # The drain's contract: any per-client task that raises is
        # awaited by a drain, which swallows the exception. So no
        # unhandled task exceptions should have reached the loop's
        # default handler.
        unhandled_msgs = [ctx.get("message", "") for ctx in unhandled]
        unhandled_excs = [ctx.get("exception") for ctx in unhandled]
        assert not unhandled, (
            f"per-client tasks fired unhandled exceptions after race "
            f"cancellation: messages={unhandled_msgs!r}, "
            f"exceptions={unhandled_excs!r}"
        )
    finally:
        loop.set_exception_handler(prev_handler)


@skip_if_trio
async def test_race_drains_losing_request_in_background() -> None:
    """Slow losing response is awaited in the background, not abandoned.

    The drain prevents zombie pending-request entries in the
    connection's state, without trying to cancel the (uncancellable)
    remote request.
    """
    fast = _StubClient(response=_selected("approve"), delay=0.0)
    # Slow loser: short enough to complete during the test.
    slow = _StubClient(response=_selected("reject"), delay=0.05)
    choices: list[ApprovalDecision] = ["approve", "reject"]

    await _race_first_response([fast, slow], _trivial_request(), choices)
    # Wait long enough for the background drain to complete the
    # slow loser's request without raising.
    await asyncio.sleep(0.15)
    # The slow client's stub recorded the request and was NOT cancelled
    # (drain awaits the natural completion).
    assert slow.cancelled is False


@skip_if_trio
async def test_race_skips_raising_client_uses_survivor() -> None:
    """First client raises (disconnect); second responds; we get the second's decision."""
    broken = _StubClient(exc=ConnectionError("disconnected"))
    good = _StubClient(response=_selected("reject"), delay=0.01)
    choices: list[ApprovalDecision] = ["approve", "reject"]
    result = await _race_first_response([broken, good], _trivial_request(), choices)
    assert result is not None
    assert result.decision == "reject"


@skip_if_trio
async def test_race_all_clients_raise_returns_none() -> None:
    """Every client errors → caller falls back to in-proc flow."""
    a = _StubClient(exc=ConnectionError("a down"))
    b = _StubClient(exc=ConnectionError("b down"))
    choices: list[ApprovalDecision] = ["approve", "reject"]
    result = await _race_first_response([a, b], _trivial_request(), choices)
    assert result is None


async def test_race_no_clients_returns_none() -> None:
    """Empty client list → None immediately, no I/O attempted."""
    choices: list[ApprovalDecision] = ["approve", "reject"]
    result = await _race_first_response([], _trivial_request(), choices)
    assert result is None


# ---------------------------------------------------------------------------
# request_human_approval_via_acp — top-level entry
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_sample_active(monkeypatch):
    """Patch sample_active to return a stub sample with an AcpSession."""

    def _patch(session: Any | None) -> None:
        sample = MagicMock()
        sample.acp_session = session
        monkeypatch.setattr(
            "inspect_ai.log._samples.sample_active",
            lambda: sample if session is not None else None,
        )

    return _patch


async def test_entry_returns_none_when_no_active_sample(monkeypatch) -> None:
    """sample_active() returns None → entry returns None (let in-proc handle it)."""
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: None)
    result = await request_human_approval_via_acp(
        message="please confirm",
        call=_make_call(),
        view=_make_view(),
        choices=["approve", "reject"],
    )
    assert result is None


async def test_entry_returns_none_when_no_acp_session(patch_sample_active) -> None:
    """Sample exists but acp_session is None → fall through."""
    patch_sample_active(None)
    result = await request_human_approval_via_acp(
        message="please confirm",
        call=_make_call(),
        view=_make_view(),
        choices=["approve", "reject"],
    )
    assert result is None


async def test_entry_returns_none_when_no_clients(patch_sample_active) -> None:
    """ACP session exists but no clients attached → fall through."""
    session = LiveAcpSession()
    patch_sample_active(session)
    result = await request_human_approval_via_acp(
        message="please confirm",
        call=_make_call(),
        view=_make_view(),
        choices=["approve", "reject"],
    )
    assert result is None


@skip_if_trio
async def test_entry_routes_to_attached_client(patch_sample_active) -> None:
    """One client attached → request routes through it; decision returns."""
    session = LiveAcpSession()
    client = _StubClient(response=_selected("approve"))
    session.attach_approver_client(client)
    patch_sample_active(session)

    result = await request_human_approval_via_acp(
        message="please confirm",
        call=_make_call(function="bash", arguments={"command": "ls"}),
        view=_make_view(),
        choices=["approve", "reject"],
    )
    assert result is not None
    assert result.decision == "approve"
    # Request received with the expected shape.
    assert len(client.received) == 1
    req = client.received[0]
    assert req.session_id == session.session_id
    assert req.tool_call.tool_call_id == "tc1"
    assert req.tool_call.title is not None
    assert req.tool_call.title.startswith("bash ")
    assert [o.option_id for o in req.options] == ["approve", "reject"]


@skip_if_trio
async def test_entry_prepends_assistant_message_as_content_block(
    patch_sample_active,
) -> None:
    """The model's accompanying message rides as the first content block.

    Pinned because the in-proc panel renders the message under an
    ``**Assistant**`` header above the view (see
    ``approval/_human/util.py:render_tool_approval``). Without
    forwarding it, the editor card is under-contextualized — the
    operator sees the tool call shape but not the "why" the agent
    gave.
    """
    session = LiveAcpSession()
    client = _StubClient(response=_selected("approve"))
    session.attach_approver_client(client)
    patch_sample_active(session)

    await request_human_approval_via_acp(
        message="I'll run ls -la to find the largest files in /tmp.",
        call=_make_call(),
        view=_make_view(),
        choices=["approve", "reject"],
    )

    req = client.received[0]
    assert req.tool_call.content is not None
    # First block is the assistant message — Assistant header + body.
    msg_block = req.tool_call.content[0]
    inner = msg_block.content
    assert hasattr(inner, "text")
    assert "**Assistant**" in inner.text
    assert "largest files" in inner.text


@skip_if_trio
async def test_entry_omits_message_block_for_empty_message(
    patch_sample_active,
) -> None:
    """An empty / whitespace-only message produces no leading block.

    Without this guard, every approval card would have an empty
    "Assistant" header padding the top of the prompt.
    """
    session = LiveAcpSession()
    client = _StubClient(response=_selected("approve"))
    session.attach_approver_client(client)
    patch_sample_active(session)

    await request_human_approval_via_acp(
        message="   \n  ",  # whitespace
        call=_make_call(),
        view=_make_view(),
        choices=["approve", "reject"],
    )

    req = client.received[0]
    # First (only) block should be the view content, NOT a stray
    # empty Assistant block.
    assert req.tool_call.content is not None
    first_block = req.tool_call.content[0]
    inner = first_block.content
    assert "**Assistant**" not in inner.text


@skip_if_trio
async def test_entry_substitutes_view_placeholders_with_call_arguments(
    patch_sample_active,
) -> None:
    """``{{param}}`` placeholders in a custom viewer resolve to argument values.

    Pinned because the in-proc panel does this substitution (see
    ``render_tool_approval`` in ``approval/_human/util.py``). Without
    matching behavior on the ACP path, custom viewers would render
    correctly in the in-proc panel but show literal
    ``{{command}}`` / ``{{path}}`` in the editor card.
    """
    session = LiveAcpSession()
    client = _StubClient(response=_selected("approve"))
    session.attach_approver_client(client)
    patch_sample_active(session)

    # Custom view with placeholders.
    view = ToolCallView(
        call=ToolCallContent(
            title="custom",
            format="markdown",
            content="Will run: `{{command}}` as user `{{user}}`",
        )
    )

    await request_human_approval_via_acp(
        message="",
        call=ToolCall(
            id="tc1",
            function="bash",
            arguments={"command": "rm -rf /tmp/x", "user": "root"},
        ),
        view=view,
        choices=["approve", "reject"],
    )

    req = client.received[0]
    assert req.tool_call.content is not None
    # The content block should have the placeholders resolved.
    rendered = ""
    for block in req.tool_call.content:
        inner = block.content
        if hasattr(inner, "text"):
            rendered += inner.text
    assert "rm -rf /tmp/x" in rendered
    assert "root" in rendered
    assert "{{command}}" not in rendered
    assert "{{user}}" not in rendered


@skip_if_trio
async def test_entry_carries_view_content_in_request(patch_sample_active) -> None:
    """The view's markdown content is forwarded as a tool_call.content block.

    Pinned so the approval prompt renders the same rich view as the
    live tool-call notification (visual consistency in Zed). The view
    block appears AFTER the assistant message block (when a message
    is present); we scan all blocks to be robust to ordering changes.
    """
    session = LiveAcpSession()
    client = _StubClient(response=_selected("approve"))
    session.attach_approver_client(client)
    patch_sample_active(session)

    await request_human_approval_via_acp(
        message="please confirm",
        call=_make_call(),
        view=_make_view(content="```bash\nls -la\n```\n"),
        choices=["approve", "reject"],
    )

    req = client.received[0]
    assert req.tool_call.content is not None
    # Scan all blocks for the view markdown — robust to layout
    # additions (assistant message, view context, etc.).
    rendered_text = ""
    for block in req.tool_call.content:
        inner = block.content
        if hasattr(inner, "text"):
            rendered_text += inner.text
    assert "ls -la" in rendered_text
    assert "```bash" in rendered_text


# ---------------------------------------------------------------------------
# End-to-end over a real socket
# ---------------------------------------------------------------------------


unix_only = pytest.mark.skipif(
    sys.platform == "win32" and not hasattr(asyncio, "start_unix_server"),
    reason="AF_UNIX sockets not available on this Windows build.",
)


@pytest.fixture
def short_data_dir(monkeypatch):
    """Short /tmp data dir so AF_UNIX paths fit in 104 chars on macOS."""
    dirpath = Path(tempfile.mkdtemp(prefix="acp_appr_", dir="/tmp"))

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


class _ClientRpcStub:
    """Line-oriented JSON-RPC client that ALSO answers a single request_permission.

    Used to simulate Zed responding to the server's outbound
    ``session/request_permission`` call. The test runs both: drives
    one normal request (initialize / session/load) for handshake,
    then waits for the server's outbound permission request and
    replies with a pre-set response.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        permission_response: dict[str, Any],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._permission_response = permission_response
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.received_permission_request: dict[str, Any] | None = None
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
                    and msg["method"] == "session/request_permission"
                    and "id" in msg
                ):
                    # Server sent us an outbound request — answer it.
                    self.received_permission_request = msg
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "result": self._permission_response,
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


@skip_if_trio
@unix_only
async def test_approval_over_real_socket_round_trip(
    short_data_dir: Path, monkeypatch
) -> None:
    """End-to-end approval flow over a real socket.

    Stubs a sample with a live session, attaches a real ACP client,
    fires request_human_approval_via_acp, asserts the wire payload
    + the response → Approval round-trip.
    """
    # Set up a fake ActiveSample so list_picker_targets has something
    # to return — needed for session/load to bind successfully.
    session = LiveAcpSession()
    # Initialize an empty session id; the real wire test below will
    # use session/load directly with the session id.
    sample = MagicMock()
    sample.acp_session = session
    sample.task = "t"
    sample.sample.id = "s"
    sample.epoch = 0
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [sample])
    monkeypatch.setattr(
        "inspect_ai.agent._acp.picker.active_samples", lambda: [sample]
    )

    async with acp_server(eval_id="evt-appr", transport=True) as server:
        assert server is not None and server.socket_path is not None
        reader, writer = await asyncio.open_unix_connection(str(server.socket_path))
        client = _ClientRpcStub(
            reader,
            writer,
            permission_response={
                "outcome": {"outcome": "selected", "optionId": "approve"}
            },
        )
        try:
            # Handshake: initialize + bind by direct loadSession.
            await client.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "test", "version": "0"},
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
            # Bind triggers the server-side handler to register itself as
            # an approver client on the session. Give the event loop one
            # tick to let _start_forwarders complete its attach.
            await asyncio.sleep(0.05)
            assert session.has_approver_clients() is True

            # Now drive the approval entry from the "agent" side.
            monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)
            result = await request_human_approval_via_acp(
                message="please confirm",
                call=_make_call(),
                view=_make_view(),
                choices=["approve", "reject"],
            )
            assert result is not None
            assert result.decision == "approve"
            # The client's stub captured the inbound request.
            assert client.received_permission_request is not None
            params = client.received_permission_request["params"]
            assert params["sessionId"] == session.session_id
            assert params["toolCall"]["title"].startswith("bash ")
            assert [o["optionId"] for o in params["options"]] == [
                "approve",
                "reject",
            ]
        finally:
            await client.close()
