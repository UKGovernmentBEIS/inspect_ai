"""SessionRow parse + binding-meta refresh tests for cancel-sample plumbing.

The widget-level coverage for the inline cancel card lives in
:mod:`test_cancel_card`. This file keeps the pure-function tests
that pin how :class:`SessionRow.fails_on_error` is parsed off the
picker-meta payload and refreshed by the binding-confirmation
notification — the two inputs the cancel card depends on to gate
its Error option.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acp.schema import AgentMessageChunk, SessionNotification, TextContentBlock

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import (
    PICKER_META_KEY,
    picker_target_meta_dict,
)
from inspect_ai.agent._acp.picker import PickerTarget
from inspect_ai.agent._acp.tui.client import (
    SessionRow,
    _refresh_row_from_binding_meta,
)

# ---------------------------------------------------------------------------
# Pure-function tests (fast loop, no Pilot)
# ---------------------------------------------------------------------------


def test_session_row_parses_fails_on_error_from_list_sessions_payload() -> None:
    """``SessionRow.fails_on_error`` reads ``failsOnError`` from the picker meta dict."""
    target = PickerTarget(
        session_id="sid",
        task="t",
        sample_id="s",
        epoch=0,
        fails_on_error=True,
    )
    payload = picker_target_meta_dict(target)
    # The TUI's parse site reads ``failsOnError`` with a default of
    # ``False`` so older servers that don't carry the field still
    # produce a usable SessionRow.
    row = SessionRow(
        eval_id="e",
        session_id=payload["sessionId"],
        task=payload["task"],
        sample_id=payload["sampleId"],
        epoch=int(payload["epoch"]),
        agent_name=payload.get("agentName"),
        started_at=payload.get("startedAt"),
        target=TargetAddress(socket_path=Path("/tmp/x.sock")),
        total_tokens=int(payload.get("totalTokens") or 0),
        fails_on_error=bool(payload.get("failsOnError", False)),
    )
    assert row.fails_on_error is True


def test_session_row_fails_on_error_defaults_false_for_older_server() -> None:
    """Older server payloads without ``failsOnError`` default to ``False`` (back-compat)."""
    # Simulated payload missing the new field — what an older server
    # responds with.
    payload: dict[str, Any] = {
        "sessionId": "sid",
        "task": "t",
        "sampleId": "s",
        "epoch": 0,
        "agentName": None,
        "startedAt": None,
        "totalTokens": 0,
    }
    row = SessionRow(
        eval_id="e",
        session_id=payload["sessionId"],
        task=payload["task"],
        sample_id=payload["sampleId"],
        epoch=int(payload["epoch"]),
        agent_name=payload.get("agentName"),
        started_at=payload.get("startedAt"),
        target=TargetAddress(socket_path=Path("/tmp/x.sock")),
        total_tokens=int(payload.get("totalTokens") or 0),
        fails_on_error=bool(payload.get("failsOnError", False)),
    )
    assert row.fails_on_error is False


# ---------------------------------------------------------------------------
# Direct-attach binding meta refresh — covers the gap where a row built
# with the default ``fails_on_error=False`` (e.g. the picker hadn't
# enumerated this session yet, or ``session/load`` was called directly
# by an editor that already knew the sessionId) gets the authoritative
# value from the server's binding-confirmation ``_meta``.
# ---------------------------------------------------------------------------


class _StubAttachedSession:
    """Minimal stand-in for AttachedSession.

    The refresh helper only touches ``session_id`` and ``row``;
    constructing a full :class:`AttachedSession` would drag in
    a real ``Connection`` for nothing.
    """

    def __init__(self, session_id: str, row: SessionRow) -> None:
        self.session_id = session_id
        self.row = row


def _bind_confirmation(
    *,
    session_id: str,
    fails_on_error: bool,
    task: str = "t",
    sample_id: str = "s",
) -> SessionNotification:
    """Build a binding-confirmation-shaped ``session/update``.

    Matches what :func:`build_picker_notification` produces for a
    single-target list (the shape ``_send_binding_confirmation``
    emits on the server).
    """
    target = PickerTarget(
        session_id=session_id,
        task=task,
        sample_id=sample_id,
        epoch=0,
        fails_on_error=fails_on_error,
    )
    notif = SessionNotification(
        session_id=session_id,
        update=AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text=f"Bound to {task}"),
        ),
    )
    notif.field_meta = {PICKER_META_KEY: [picker_target_meta_dict(target)]}
    return notif


def test_binding_meta_refresh_promotes_fails_on_error() -> None:
    """Direct-attach row default ``False`` is promoted from binding-confirmation meta."""
    row = SessionRow(
        eval_id="e",
        session_id="sid-x",
        task="t",
        sample_id="s",
        epoch=0,
        agent_name=None,
        started_at=None,
        target=TargetAddress(socket_path=Path("/tmp/x.sock")),
        fails_on_error=False,
    )
    session = _StubAttachedSession(session_id="sid-x", row=row)
    notif = _bind_confirmation(session_id="sid-x", fails_on_error=True)
    _refresh_row_from_binding_meta(session, notif)  # type: ignore[arg-type]
    assert session.row.fails_on_error is True


def test_binding_meta_refresh_skips_mismatched_session_id() -> None:
    """Notification for another session must not touch our row."""
    row = SessionRow(
        eval_id="e",
        session_id="sid-x",
        task="t",
        sample_id="s",
        epoch=0,
        agent_name=None,
        started_at=None,
        target=TargetAddress(socket_path=Path("/tmp/x.sock")),
        fails_on_error=False,
    )
    session = _StubAttachedSession(session_id="sid-x", row=row)
    notif = _bind_confirmation(session_id="other-sid", fails_on_error=True)
    _refresh_row_from_binding_meta(session, notif)  # type: ignore[arg-type]
    assert session.row.fails_on_error is False


def test_binding_meta_refresh_is_noop_without_picker_meta() -> None:
    """Plain session/update notifications leave the row untouched."""
    row = SessionRow(
        eval_id="e",
        session_id="sid-x",
        task="t",
        sample_id="s",
        epoch=0,
        agent_name=None,
        started_at=None,
        target=TargetAddress(socket_path=Path("/tmp/x.sock")),
        fails_on_error=False,
    )
    session = _StubAttachedSession(session_id="sid-x", row=row)
    notif = SessionNotification(
        session_id="sid-x",
        update=AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="hello"),
        ),
    )
    _refresh_row_from_binding_meta(session, notif)  # type: ignore[arg-type]
    assert session.row.fails_on_error is False
