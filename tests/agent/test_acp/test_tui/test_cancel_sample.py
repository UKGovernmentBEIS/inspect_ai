"""Tests for the composer-area cancel-sample bar.

Covers the pure-function helpers (SessionRow parse, binding-meta
refresh) without ``--runslow``, plus pilot-driven integration tests
that exercise the bar through the real App + SessionScreen path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from acp.schema import AgentMessageChunk, SessionNotification, TextContentBlock
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_CANCEL_SAMPLE_METHOD,
    PICKER_META_KEY,
    picker_target_meta_dict,
)
from inspect_ai.agent._acp.picker import PickerTarget
from inspect_ai.agent._acp.tui.app import InspectAcpApp
from inspect_ai.agent._acp.tui.client import (
    SessionRow,
    _refresh_row_from_binding_meta,
)
from inspect_ai.agent._acp.tui.session_screen import SessionScreen
from inspect_ai.agent._acp.tui.widgets._prompt import _PromptOption
from inspect_ai.agent._acp.tui.widgets.cancel_sample import (
    _BUTTON_ID_PREFIX,
    _CancelSampleBar,
)

from .conftest import make_fake_client

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


# ---------------------------------------------------------------------------
# Pilot integration tests (require --runslow)
# ---------------------------------------------------------------------------


def _row(fails_on_error: bool = False) -> SessionRow:
    """Build a SessionRow for pilot tests."""
    return SessionRow(
        eval_id="eval-x",
        session_id="sid-x",
        task="t",
        sample_id="s1",
        epoch=1,
        agent_name="react",
        started_at=1_700_000_000.0,
        target=TargetAddress(socket_path=Path("/tmp/acp_cancel_test.sock")),
        fails_on_error=fails_on_error,
    )


async def _open_session_screen(pilot: Any, rows: list[SessionRow]) -> SessionScreen:
    """Walk PickerScreen → SessionScreen via the picker's ``_on_select``."""
    app = pilot.app
    await pilot.pause()
    if not isinstance(app.screen, SessionScreen):
        app.screen._on_select(rows[0])
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, SessionScreen):
                break
    assert isinstance(app.screen, SessionScreen)
    return app.screen


def _cancel_bar(screen: SessionScreen) -> _CancelSampleBar:
    return screen.query_one(_CancelSampleBar)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_n_shows_cancel_bar() -> None:
    """``^N`` flips the cancel-sample bar visible (composer + approval bar hide)."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        bar = _cancel_bar(screen)
        assert not bar.is_visible
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert bar.is_visible


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_escape_dismisses_cancel_bar_without_sending_request() -> None:
    """``escape`` hides the bar without firing a cancel request."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        bar = _cancel_bar(screen)
        assert bar.is_visible
        await pilot.press("escape")
        await pilot.pause()
        assert not bar.is_visible
        # No JSON-RPC request crossed the wire — the bar dismiss is
        # a pure UI no-op when the operator backs out.
        requests = screen._session.connection.requests
        assert not any(m == INSPECT_CANCEL_SAMPLE_METHOD for m, _ in requests)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_two_choice_bar_mounts_score_error_and_back() -> None:
    """``fails_on_error=False`` → score, error, and back options all mount."""
    rows = [_row(fails_on_error=False)]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        bar = _cancel_bar(screen)
        action_ids = [o.action_id for o in bar.query(_PromptOption)]
        assert action_ids == ["score", "error", "back"]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_single_choice_bar_hides_error_option() -> None:
    """``fails_on_error=True`` → error option suppressed; only score + back mount."""
    rows = [_row(fails_on_error=True)]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        bar = _cancel_bar(screen)
        action_ids = [o.action_id for o in bar.query(_PromptOption)]
        assert action_ids == ["score", "back"]


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_score_option_focused_on_show() -> None:
    """``[s] Cancel: Score`` receives focus on show so Enter activates it."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        focused = screen.focused
        assert focused is not None
        assert focused.id == f"{_BUTTON_ID_PREFIX}score"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_bare_letter_s_fires_score_request() -> None:
    """Pressing ``s`` sends ``inspect/cancel_sample`` with ``action="score"``."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert _cancel_bar(screen).is_visible
        await pilot.press("s")
        # Pause enough ticks for the worker to fire the request and
        # the bar to hide.
        for _ in range(10):
            await pilot.pause()
            if not _cancel_bar(screen).is_visible:
                break
        assert not _cancel_bar(screen).is_visible
        requests = screen._session.connection.requests  # type: ignore[attr-defined]
        matching = [(m, p) for m, p in requests if m == INSPECT_CANCEL_SAMPLE_METHOD]
        assert len(matching) == 1, requests
        _, params = matching[0]
        assert params == {"sessionId": "sid-x", "action": "score"}


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_bare_letter_e_fires_error_request_when_allowed() -> None:
    """``fails_on_error=False`` → pressing ``e`` sends ``action="error"``."""
    rows = [_row(fails_on_error=False)]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("e")
        for _ in range(10):
            await pilot.pause()
            if not _cancel_bar(screen).is_visible:
                break
        assert not _cancel_bar(screen).is_visible
        requests = screen._session.connection.requests  # type: ignore[attr-defined]
        matching = [(m, p) for m, p in requests if m == INSPECT_CANCEL_SAMPLE_METHOD]
        assert len(matching) == 1, requests
        _, params = matching[0]
        assert params == {"sessionId": "sid-x", "action": "error"}


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_bare_letter_e_is_noop_when_fails_on_error_true() -> None:
    """``fails_on_error=True`` → ``e`` is a no-op (no request, bar stays up)."""
    rows = [_row(fails_on_error=True)]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert _cancel_bar(screen).is_visible
        await pilot.press("e")
        # Give the framework time to (not) dismiss; bar must stay up.
        for _ in range(5):
            await pilot.pause()
        assert _cancel_bar(screen).is_visible
        requests = screen._session.connection.requests  # type: ignore[attr-defined]
        assert not any(m == INSPECT_CANCEL_SAMPLE_METHOD for m, _ in requests)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_enter_on_focused_score_option_fires_score_request() -> None:
    """Enter on the auto-focused score option activates it (no bare-letter needed)."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        focused = screen.focused
        assert focused is not None and focused.id == f"{_BUTTON_ID_PREFIX}score"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if not _cancel_bar(screen).is_visible:
                break
        assert not _cancel_bar(screen).is_visible
        requests = screen._session.connection.requests  # type: ignore[attr-defined]
        matching = [(m, p) for m, p in requests if m == INSPECT_CANCEL_SAMPLE_METHOD]
        assert len(matching) == 1
        assert matching[0][1]["action"] == "score"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_tab_from_score_advances_to_back_in_single_choice_bar() -> None:
    """Single-choice bar: Tab from score lands on back (error is hidden)."""
    rows = [_row(fails_on_error=True)]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        focused = screen.focused
        assert focused is not None
        # Tab from score lands on back (error is hidden).
        assert focused.id == f"{_BUTTON_ID_PREFIX}back"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_tab_from_score_advances_to_error_in_two_choice_bar() -> None:
    """Two-choice bar: Tab cycles score → error → back."""
    rows = [_row(fails_on_error=False)]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        focused = screen.focused
        assert focused is not None
        assert focused.id == f"{_BUTTON_ID_PREFIX}error"
        await pilot.press("tab")
        await pilot.pause()
        focused = screen.focused
        assert focused is not None
        assert focused.id == f"{_BUTTON_ID_PREFIX}back"


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_back_option_dismisses_without_request() -> None:
    """Activating the ``[esc] Go Back`` option dismisses without a JSON-RPC call."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        await pilot.press("ctrl+n")
        await pilot.pause()
        # Tab to back, then Enter.
        await pilot.press("tab")
        await pilot.press("tab")
        await pilot.pause()
        focused = screen.focused
        assert focused is not None and focused.id == f"{_BUTTON_ID_PREFIX}back"
        await pilot.press("enter")
        await pilot.pause()
        assert not _cancel_bar(screen).is_visible
        requests = screen._session.connection.requests  # type: ignore[attr-defined]
        assert not any(m == INSPECT_CANCEL_SAMPLE_METHOD for m, _ in requests)


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_composer_input_hidden_while_cancel_bar_visible() -> None:
    """Cancel bar takes the row: the composer ``Input`` hides while it's up."""
    from textual.widgets import Input

    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        composer = screen.query_one("#composer", Input)
        assert composer.display
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert not composer.display
        await pilot.press("escape")
        await pilot.pause()
        assert composer.display


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_ctrl_n_noop_when_lifecycle_complete() -> None:
    """``^N`` after the sample completes is a no-op (nothing to cancel)."""
    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        screen = await _open_session_screen(pilot, rows)
        screen.state.mark_complete()
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()
        # Cancel bar must stay hidden.
        assert not _cancel_bar(screen).is_visible


@skip_if_trio
@pytest.mark.slow
@pytest.mark.anyio
async def test_footer_right_cluster_is_flushed_right() -> None:
    """`cancel sample`, `switch sample`, `quit` cluster on the right of the footer.

    Verifies the :class:`AppFooter` layout: the spacer widget sits
    between the everyday command keys and the right cluster, and the
    right cluster reads ``cancel | switch | quit`` in that order
    (independent of binding discovery order).
    """
    from inspect_ai.agent._acp.tui.widgets.footer import AppFooter, _FooterSpacer

    rows = [_row()]
    client = make_fake_client(rows)
    app = InspectAcpApp(eval_id=None, server=None, client=client)
    async with app.run_test() as pilot:
        await _open_session_screen(pilot, rows)
        footer = app.screen.query_one(AppFooter)
        # Walk the footer's children. The order is what the operator
        # sees left-to-right; assert (a) a spacer is present, and
        # (b) the three right-cluster actions follow the spacer in
        # the canonical order.
        children = list(footer.children)
        spacer_indices = [
            i for i, c in enumerate(children) if isinstance(c, _FooterSpacer)
        ]
        assert len(spacer_indices) == 1, (
            f"expected exactly one footer spacer, found {len(spacer_indices)}"
        )
        spacer_at = spacer_indices[0]
        actions_after_spacer = [
            getattr(c, "action", None) for c in children[spacer_at + 1 :]
        ]
        # Filter to the cluster actions (other widgets — labels, groups —
        # have action=None and shouldn't appear, but the filter keeps
        # the assertion robust if Textual's Footer ever interleaves
        # non-FooterKey widgets).
        cluster = [
            a
            for a in actions_after_spacer
            if a in {"cancel_sample", "switch_sample", "quit"}
        ]
        assert cluster == ["cancel_sample", "switch_sample", "quit"], (
            f"right cluster order wrong: {cluster}"
        )
        # And nothing from the right cluster appears BEFORE the spacer.
        before_spacer = [getattr(c, "action", None) for c in children[:spacer_at]]
        assert not any(
            a in {"cancel_sample", "switch_sample", "quit"} for a in before_spacer
        ), f"right-cluster action leaked into left group: {before_spacer}"
