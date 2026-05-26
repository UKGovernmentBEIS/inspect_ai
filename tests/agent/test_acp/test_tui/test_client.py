"""Integration tests for the TUI client helpers against a real `AcpServer`.

These tests spin up an in-process AF_UNIX ACP server, populate
`picker.active_samples` with controlled stubs, and verify that
`enumerate_sessions` / `attach_session` round-trip correctly through
the real wire protocol — exercising the picker payload extensions
(#1 startedAt, #5 agentName) end-to-end.

Marked ``slow`` at module level: each test boots a real ACP server
over a temp AF_UNIX socket, runs a JSON-RPC round-trip, then tears
down — meaningfully more expensive than the in-memory tests in
:mod:`test_picker`. Run with ``pytest --runslow`` to include them.
"""

from __future__ import annotations

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
from inspect_ai.agent._acp.tui.client import (
    CLIENT_CAPABILITIES,
    attach_session,
    enumerate_sessions,
)
from inspect_ai.agent._acp.tui.state import SessionState

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX-only test")

pytestmark = pytest.mark.slow


def _make_active_sample(
    *,
    task: str,
    sample_id: str,
    epoch: int,
    session_id: str,
    agent_name: str | None = "react",
    started: float | None = 1_700_000_000.0,
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
    active.agent_name = agent_name
    active.started = started
    # MUST be a real int / bool — list_picker_targets reads these into
    # a PickerTarget that's later JSON-serialized over the wire. An
    # unset MagicMock attribute returns a MagicMock that the encoder
    # can't handle, and the server's request handler crashes silently
    # in a background task, leaving the client awaiting forever.
    active.total_messages = total_messages
    active.total_tokens = total_tokens
    active.fails_on_error = fails_on_error
    sess = MagicMock()
    sess.session_id = session_id
    active.acp_transport = sess
    return active


@pytest.fixture
def short_data_dir(monkeypatch):
    dirpath = Path(tempfile.mkdtemp(prefix="acp_tui_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("inspect_ai.agent._acp.discovery.inspect_data_dir", _stub)
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


@pytest.fixture
def stub_targets(monkeypatch):
    def _set(samples: list[Any]) -> None:
        monkeypatch.setattr(picker, "active_samples", lambda: samples)

    return _set


@skip_if_trio
@unix_only
async def test_enumerate_returns_rows_with_new_fields(
    short_data_dir: Path, stub_targets
) -> None:
    """`enumerate_sessions` carries agentName + startedAt through the wire."""
    stub_targets(
        [
            _make_active_sample(
                task="t1",
                sample_id="s1",
                epoch=0,
                session_id="uuid-a",
                agent_name="react",
                started=1_700_000_111.0,
            ),
        ]
    )
    async with acp_server(eval_id="evt-tui", transport=True) as server:
        assert server is not None
        target = TargetAddress(socket_path=server.socket_path)
        rows = await enumerate_sessions([("evt-tui", target)])
        assert len(rows) == 1
        row = rows[0]
        assert row.eval_id == "evt-tui"
        assert row.session_id == "uuid-a"
        assert row.task == "t1"
        assert row.sample_id == "s1"
        assert row.epoch == 0
        assert row.agent_name == "react"
        assert row.started_at == 1_700_000_111.0
        assert row.target is target


@skip_if_trio
@unix_only
async def test_enumerate_drops_per_address_failures(
    short_data_dir: Path, stub_targets, capsys
) -> None:
    """One unreachable address must not blank the surviving rows."""
    stub_targets(
        [_make_active_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a")]
    )
    async with acp_server(eval_id="evt-good", transport=True) as server:
        assert server is not None
        good = TargetAddress(socket_path=server.socket_path)
        bad = TargetAddress(socket_path=Path("/tmp/does-not-exist.sock"))
        rows = await enumerate_sessions([("evt-bad", bad), ("evt-good", good)])
        assert [r.eval_id for r in rows] == ["evt-good"]
    err = capsys.readouterr().err
    assert "does-not-exist.sock" in err


@skip_if_trio
@unix_only
async def test_enumerate_applies_eval_id_filter(
    short_data_dir: Path, stub_targets
) -> None:
    stub_targets(
        [
            _make_active_sample(
                task="t1", sample_id="s1", epoch=0, session_id="uuid-a"
            ),
        ]
    )
    async with acp_server(eval_id="evt-tui-f", transport=True) as server:
        assert server is not None
        target = TargetAddress(socket_path=server.socket_path)
        rows = await enumerate_sessions(
            [("evt-tui-f", target)], eval_id_filter="something-else"
        )
        assert rows == []


@skip_if_trio
@unix_only
async def test_attach_session_binds_via_session_load(
    short_data_dir: Path, stub_targets
) -> None:
    """`attach_session` opens a fresh connection bound via session/load."""
    stub_targets(
        [
            _make_active_sample(
                task="t1", sample_id="s1", epoch=0, session_id="uuid-attach"
            )
        ]
    )
    async with acp_server(eval_id="evt-attach", transport=True) as server:
        assert server is not None
        target = TargetAddress(socket_path=server.socket_path)
        rows = await enumerate_sessions([("evt-attach", target)])
        assert len(rows) == 1
        attached = await attach_session(rows[0], state=SessionState())
        try:
            assert attached.is_connected
            assert attached.session_id == "uuid-attach"
        finally:
            await attached.close()
            assert not attached.is_connected


# ---------------------------------------------------------------------------
# Plan-rendering opt-in (verifies the TUI sends the right capability flag)
# ---------------------------------------------------------------------------


_EXPECTED_RAW_EVENTS = [
    "score",
    "sample_limit",
    "error",
    "compaction",
    "info",
    "span_begin",
    "span_end",
]
"""Expected raw-event subscription list the TUI advertises at initialize.

Score events drive the mid-stream score chip; sample_limit / error /
compaction / info drive the Inspect-native event chips; span_begin /
span_end drive the scoring-phase boundary detection. Kept as a
single constant so the three tests below (and any future addition)
expand from one source rather than re-typing the list."""


def test_client_capabilities_advertises_plan_rendering_and_event_subscription() -> None:
    """Unit check: the constant ships ``inspect.plan_rendering`` + raw-event subscription.

    Both ``_list_for_target`` and ``attach_session`` send this dict
    verbatim in their ``initialize`` request, so a single
    structure-level assertion covers both code paths.
    """
    assert CLIENT_CAPABILITIES == {
        "_meta": {
            "inspect.plan_rendering": True,
            "inspect.raw_events": _EXPECTED_RAW_EVENTS,
        }
    }


@skip_if_trio
@unix_only
async def test_enumerate_session_initialize_sets_plan_rendering(
    short_data_dir: Path, stub_targets, monkeypatch
) -> None:
    """The server sees ``client_renders_plan = True`` after enumerate.

    Spies on ``detect_capabilities`` so we don't depend on the server
    exposing per-connection state directly. The capability check fires
    once per connection in ``ConnectionHandler.initialize``.
    """
    captured: list[Any] = []

    import inspect_ai.agent._acp.connection as connection_mod
    from inspect_ai.agent._acp.inspect_ext import detect_capabilities

    def _spy(
        client_info: Any, client_capabilities: Any
    ) -> tuple[bool, frozenset[str] | None]:
        captured.append((client_info, client_capabilities))
        return detect_capabilities(client_info, client_capabilities)

    monkeypatch.setattr(connection_mod, "detect_capabilities", _spy)

    stub_targets(
        [_make_active_sample(task="t", sample_id="s", epoch=0, session_id="uuid")]
    )
    async with acp_server(eval_id="evt-plan-enum", transport=True) as server:
        assert server is not None
        target = TargetAddress(socket_path=server.socket_path)
        await enumerate_sessions([("evt-plan-enum", target)])

    assert len(captured) == 1, (
        f"expected one initialize call from enumerate, got {captured}"
    )
    client_info, client_capabilities = captured[0]
    assert client_info is not None
    assert client_info.name == "inspect-acp-tui"
    assert client_capabilities is not None
    assert client_capabilities.field_meta == {
        "inspect.plan_rendering": True,
        "inspect.raw_events": _EXPECTED_RAW_EVENTS,
    }


@skip_if_trio
@unix_only
async def test_attach_session_initialize_sets_plan_rendering(
    short_data_dir: Path, stub_targets, monkeypatch
) -> None:
    """The server sees ``client_renders_plan = True`` after attach.

    The two paths (``enumerate`` and ``attach``) share the same
    ``CLIENT_CAPABILITIES`` constant, but a regression on either one
    breaks plan rendering, so each gets its own integration check.
    """
    captured: list[Any] = []

    import inspect_ai.agent._acp.connection as connection_mod
    from inspect_ai.agent._acp.inspect_ext import detect_capabilities

    def _spy(
        client_info: Any, client_capabilities: Any
    ) -> tuple[bool, frozenset[str] | None]:
        captured.append((client_info, client_capabilities))
        return detect_capabilities(client_info, client_capabilities)

    monkeypatch.setattr(connection_mod, "detect_capabilities", _spy)

    stub_targets(
        [
            _make_active_sample(
                task="t1", sample_id="s1", epoch=0, session_id="uuid-attach-plan"
            )
        ]
    )
    async with acp_server(eval_id="evt-plan-attach", transport=True) as server:
        assert server is not None
        target = TargetAddress(socket_path=server.socket_path)
        # enumerate first (also opts in — captured), then attach
        # (second capture). The second one is the bound long-lived
        # connection that actually consumes the plan notifications.
        rows = await enumerate_sessions([("evt-plan-attach", target)])
        attached = await attach_session(rows[0], state=SessionState())
        try:
            assert attached.is_connected
        finally:
            await attached.close()

    # Two connections: enumerate (closed after list) + attach (live).
    # Both must carry the opt-in.
    assert len(captured) == 2, captured
    for client_info, client_capabilities in captured:
        assert client_info.name == "inspect-acp-tui"
        assert client_capabilities.field_meta == {
            "inspect.plan_rendering": True,
            "inspect.raw_events": _EXPECTED_RAW_EVENTS,
        }


# ---------------------------------------------------------------------------
# session/request_permission handler (response shape + cancellation path)
# ---------------------------------------------------------------------------


def _permission_request_dict(
    tool_call_id: str = "tc-1",
    *,
    option_ids: tuple[str, ...] = ("approve", "reject"),
) -> dict[str, Any]:
    """JSON-RPC params payload mirroring what the server would send."""
    options = [
        {"optionId": oid, "name": oid.capitalize(), "kind": "allow_once"}
        for oid in option_ids
    ]
    return {
        "sessionId": "sid",
        "toolCall": {
            "toolCallId": tool_call_id,
            "title": "bash ls",
            "status": "pending",
            "rawInput": {"command": "ls"},
            "content": [],
        },
        "options": options,
    }


@skip_if_trio
async def test_permission_handler_returns_allowed_outcome_for_chosen_option() -> None:
    """Handler resolves with ``AllowedOutcome(option_id=...)`` on operator click."""
    import asyncio

    from inspect_ai.agent._acp.tui.client import _make_permission_handler
    from inspect_ai.agent._acp.tui.state import PendingApproval

    captured: list[PendingApproval] = []

    def _callback(pending: PendingApproval) -> None:
        captured.append(pending)

        # Simulate the operator clicking Approve on the next event-loop tick.
        async def _resolve() -> None:
            await asyncio.sleep(0)
            pending.chosen_option_id = "approve"
            pending.event.set()

        asyncio.create_task(_resolve())

    handler = _make_permission_handler(_callback)
    response = await handler(_permission_request_dict())

    assert response["outcome"]["outcome"] == "selected"
    assert response["outcome"]["optionId"] == "approve"
    # Sanity: the handler did hand the pending to the callback.
    assert len(captured) == 1
    assert captured[0].request.tool_call.tool_call_id == "tc-1"


@skip_if_trio
async def test_permission_handler_returns_denied_outcome_for_cancelled() -> None:
    """Handler resolves with ``DeniedOutcome(cancelled)`` when no choice was made."""
    import asyncio

    from inspect_ai.agent._acp.tui.client import _make_permission_handler
    from inspect_ai.agent._acp.tui.state import PendingApproval

    def _callback(pending: PendingApproval) -> None:
        async def _resolve() -> None:
            await asyncio.sleep(0)
            pending.cancelled = True
            pending.event.set()

        asyncio.create_task(_resolve())

    handler = _make_permission_handler(_callback)
    response = await handler(_permission_request_dict())

    assert response["outcome"]["outcome"] == "cancelled"
    # AllowedOutcome's optionId field is absent in DeniedOutcome.
    assert "optionId" not in response["outcome"]


@skip_if_trio
async def test_permission_handler_propagates_cancellation_and_marks_pending() -> None:
    """``CancelledError`` (screen unmount) flips ``pending.cancelled`` + re-raises."""
    import asyncio

    from inspect_ai.agent._acp.tui.client import _make_permission_handler
    from inspect_ai.agent._acp.tui.state import PendingApproval

    captured: list[PendingApproval] = []

    def _callback(pending: PendingApproval) -> None:
        captured.append(pending)
        # Never resolve — leave the handler parked.

    handler = _make_permission_handler(_callback)
    task = asyncio.create_task(handler(_permission_request_dict()))
    # Let the handler's callback fire + park.
    await asyncio.sleep(0)
    assert len(captured) == 1
    pending = captured[0]
    assert not pending.event.is_set()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Pending was marked cancelled + event fired (so any concurrent
    # reader sees a consistent state).
    assert pending.cancelled is True
    assert pending.event.is_set()


@skip_if_trio
async def test_permission_handler_propagates_callback_exception_and_marks_pending() -> (
    None
):
    """Synchronous exception from the screen callback also fires ``pending.event``.

    Pinned regression: an earlier revision called
    ``on_request_permission(pending)`` BEFORE entering the
    try/except, so a sync throw from the screen-side handler (e.g.
    a Textual ``NoMatches`` if the screen has just unmounted)
    propagated out without setting ``pending.event``. Any
    concurrent reader holding the ``PendingApproval`` reference
    would observe a half-initialised slot, and the server-side
    request future would be permanently parked. The fix moves the
    callback invocation inside the try block so cancellation +
    sync-exception paths both flip the flag and signal the event.
    """
    from inspect_ai.agent._acp.tui.client import _make_permission_handler
    from inspect_ai.agent._acp.tui.state import PendingApproval

    captured: list[PendingApproval] = []

    def _callback(pending: PendingApproval) -> None:
        # Grab the reference BEFORE raising so the test can inspect
        # post-throw state.
        captured.append(pending)
        raise RuntimeError("screen unmounted")

    handler = _make_permission_handler(_callback)
    with pytest.raises(RuntimeError, match="screen unmounted"):
        await handler(_permission_request_dict())

    assert len(captured) == 1
    pending = captured[0]
    # Marked cancelled + event fired despite the synchronous throw.
    assert pending.cancelled is True
    assert pending.event.is_set()
