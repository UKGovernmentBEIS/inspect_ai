"""Tests for Phase 6 client-side reconnect machinery.

Three layers:

1. **State-level**: ``SessionState.mark_disconnected`` /
   ``mark_reconnected`` / ``mark_session_ended_received`` /
   ``disconnected`` property — pure, sub-millisecond.
2. **Coordinator unit tests**: drive ``AttachedSession._coordinator``
   with a fake ``_establish_connection`` so the reconnect cycle runs
   without real sockets. Verifies the session_ended gate, the
   invalid_params handling, the toast cadence, and the
   mark_disconnected → mark_reconnected sequence.
3. **Pilot tests**: end-to-end via Textual's ``Pilot`` for the
   send-while-disconnected guard.

The pilot tests are marked ``slow`` via module pytestmark on the
classes; pure tests run on every collection.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.exceptions import RequestError
from test_helpers.utils import skip_if_trio

from inspect_ai.agent._acp.tui.client import (
    _DISCONNECT_TOAST_INTERVAL_SECONDS,
    _JSONRPC_INVALID_PARAMS,
    _RECONNECT_BACKOFF,
    AttachedSession,
)
from inspect_ai.agent._acp.tui.state import SessionState

# ---------------------------------------------------------------------------
# State-level: pure, no event loop
# ---------------------------------------------------------------------------


def test_mark_disconnected_sets_flag_and_notifies() -> None:
    state = SessionState()
    notifications: list[None] = []
    state.subscribe(lambda: notifications.append(None))
    assert state.disconnected is False
    state.mark_disconnected()
    assert state.disconnected is True
    assert len(notifications) == 1


def test_mark_disconnected_is_idempotent() -> None:
    state = SessionState()
    notifications: list[None] = []
    state.subscribe(lambda: notifications.append(None))
    state.mark_disconnected()
    state.mark_disconnected()
    state.mark_disconnected()
    assert state.disconnected is True
    assert len(notifications) == 1


def test_mark_reconnected_clears_flag_and_notifies() -> None:
    state = SessionState()
    state.mark_disconnected()
    notifications: list[None] = []
    state.subscribe(lambda: notifications.append(None))
    state.mark_reconnected()
    assert state.disconnected is False
    assert len(notifications) == 1


def test_mark_reconnected_noop_when_not_disconnected() -> None:
    state = SessionState()
    notifications: list[None] = []
    state.subscribe(lambda: notifications.append(None))
    state.mark_reconnected()
    assert state.disconnected is False
    assert notifications == []


def test_mark_session_ended_received_sets_flag() -> None:
    state = SessionState()
    assert state.session_ended_received is False
    state.mark_session_ended_received()
    assert state.session_ended_received is True
    # Sticky idempotent
    state.mark_session_ended_received()
    assert state.session_ended_received is True


def test_session_ended_blocks_subsequent_mark_disconnected() -> None:
    """A clean session end must NOT register as a transient disconnect.

    Without this guard, the brief window between ``mark_complete``
    and the actual socket EOF would flash the dot amber.
    """
    state = SessionState()
    state.mark_session_ended_received()
    state.mark_complete()
    notifications: list[None] = []
    state.subscribe(lambda: notifications.append(None))
    state.mark_disconnected()
    assert state.disconnected is False
    assert notifications == []


def test_mark_complete_clears_disconnected_flag() -> None:
    """Terminal sessions don't show an amber dot in the postmortem view."""
    state = SessionState()
    state.mark_disconnected()
    assert state.disconnected is True
    state.mark_complete()
    # ``disconnected`` property is gated on NOT complete — terminal
    # sessions always read as connected even if the underlying flag
    # was left True by a race.
    assert state.disconnected is False


def test_disconnected_property_is_orthogonal_to_lifecycle() -> None:
    """``disconnected`` is about transport health; ``lifecycle`` is agent-side.

    Both can be set independently: a brief socket blip during a
    "running" agent shouldn't fold the two together.
    """
    state = SessionState()
    # Simulate "agent working" by stamping the running-window
    # timestamp. ``has_active_work`` is False (no pending message,
    # no in-flight tool), so we use the quiescence tail instead.
    state._last_running_at = state._now()
    assert state.lifecycle == "running"
    assert state.disconnected is False
    state.mark_disconnected()
    assert state.disconnected is True
    # Lifecycle is unchanged by disconnect.
    assert state.lifecycle == "running"


# ---------------------------------------------------------------------------
# Coordinator unit tests — mock _establish_connection
# ---------------------------------------------------------------------------


class _FakeSleep:
    """Async sleep stub that records arguments without actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)
        # Yield once so other tasks can run; do not actually sleep.
        await asyncio.sleep(0)


class _FakeClock:
    """Synthetic monotonic clock advanced by the test."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _make_session(
    *,
    state: SessionState | None = None,
    notify: Any = None,
    sleep: Any = None,
    clock: Any = None,
) -> AttachedSession:
    """Build a bare AttachedSession for coordinator-only tests.

    Does NOT call ``_establish_connection``; tests substitute the
    method on the instance to control reconnect behavior.
    """
    state = state if state is not None else SessionState()
    session = AttachedSession(
        connection=MagicMock(),
        writer=MagicMock(),
        session_id="sid-1",
        row=MagicMock(),
        state=state,
        notify=notify,
        sleep=sleep if sleep is not None else asyncio.sleep,
        clock=clock if clock is not None else (lambda: 0.0),
    )
    return session


@skip_if_trio
async def test_reconnect_loop_backoff_schedule_is_exponential_then_capped() -> None:
    """Backoff sequence: 1, 2, 4, 8, 16, 30, 30, ... seconds."""
    state = SessionState()
    sleep = _FakeSleep()
    session = _make_session(state=state, sleep=sleep)
    # Always-fails reconnect so we observe many attempts.
    attempts = 0

    async def _fail_to_reconnect() -> None:
        nonlocal attempts
        attempts += 1
        if attempts >= 8:
            # Stop the loop by signalling close so the coordinator returns.
            session._closed = True
        raise OSError("nope")

    session._establish_connection = _fail_to_reconnect  # type: ignore[method-assign]
    # Drive only the reconnect loop directly (skips coordinator setup).
    result = await session._reconnect_until_resolved()
    assert result is False  # closed, not session-gone
    # First six sleeps follow _RECONNECT_BACKOFF verbatim; after that
    # the cap (last entry, 30) repeats.
    expected_prefix = list(_RECONNECT_BACKOFF)
    assert sleep.calls[: len(expected_prefix)] == expected_prefix
    # Subsequent sleeps stay at the cap (30s = _RECONNECT_BACKOFF[-1]).
    cap = _RECONNECT_BACKOFF[-1]
    assert all(s == cap for s in sleep.calls[len(expected_prefix) :])


@skip_if_trio
async def test_reconnect_loop_returns_true_on_invalid_params() -> None:
    """``session/load`` returning ``invalid_params`` → session gone."""
    state = SessionState()
    sleep = _FakeSleep()
    session = _make_session(state=state, sleep=sleep)

    async def _gone() -> None:
        raise RequestError(_JSONRPC_INVALID_PARAMS, "Invalid params")

    session._establish_connection = _gone  # type: ignore[method-assign]
    result = await session._reconnect_until_resolved()
    assert result is True


@skip_if_trio
async def test_reconnect_loop_keeps_retrying_on_non_invalid_params_errors() -> None:
    """Other JSON-RPC errors (server transiently mis-routing) → retry."""
    state = SessionState()
    sleep = _FakeSleep()
    session = _make_session(state=state, sleep=sleep)
    attempts = 0

    async def _flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RequestError(-32603, "Internal error")  # not invalid_params
        if attempts == 2:
            raise RequestError(-32601, "Method not found")
        # Third attempt succeeds.
        return None

    session._establish_connection = _flaky  # type: ignore[method-assign]
    result = await session._reconnect_until_resolved()
    assert result is False  # success
    assert attempts == 3


@skip_if_trio
async def test_reconnect_loop_keeps_retrying_on_transport_errors() -> None:
    """OSError / ConnectionError (socket dead) → retry forever until success."""
    state = SessionState()
    sleep = _FakeSleep()
    session = _make_session(state=state, sleep=sleep)
    attempts = 0

    async def _flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("connection refused")
        if attempts < 5:
            raise ConnectionError("reset by peer")
        return None

    session._establish_connection = _flaky  # type: ignore[method-assign]
    result = await session._reconnect_until_resolved()
    assert result is False
    assert attempts == 5


@skip_if_trio
async def test_toast_cadence_fires_after_60_seconds() -> None:
    """First "still reconnecting" toast fires at >= 60s of disconnect."""
    state = SessionState()
    clock = _FakeClock(start=0.0)
    notifications: list[tuple[str, str]] = []

    def _notify(msg: str, severity: str) -> None:
        notifications.append((msg, severity))

    sleep_advances: list[float] = []

    async def _sleep(delay: float) -> None:
        sleep_advances.append(delay)
        clock.advance(delay)
        await asyncio.sleep(0)

    session = _make_session(
        state=state,
        notify=_notify,
        sleep=_sleep,
        clock=clock,
    )
    session._disconnected_at = clock()
    # Run the toast cadence task for a brief window, then cancel.
    task = asyncio.create_task(session._toast_cadence())
    # Let it fire two toasts then cancel (we yield enough times for
    # both inner sleeps + notify calls to land).
    for _ in range(50):
        await asyncio.sleep(0)
        if len(notifications) >= 2:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # First toast fires at the 60s sleep boundary; second at 120s.
    assert sleep_advances[0] == _DISCONNECT_TOAST_INTERVAL_SECONDS
    assert len(notifications) >= 2
    assert "Reconnecting to ACP server" in notifications[0][0]
    assert notifications[0][1] == "warning"
    # Elapsed-time formatting: second toast >= 2 minutes.
    assert "2 minute" in notifications[1][0]


@skip_if_trio
async def test_session_ended_handler_sets_terminal_disconnected_event() -> None:
    """``inspect/session_ended`` must set ``session.disconnected`` for teardown.

    Regression: the server keeps the transport OPEN after sending
    ``inspect/session_ended`` (per ``session_router.py:331-340`` —
    the connection is reusable for picker → another sample). The
    receive loop therefore won't exit on its own. The handler must
    explicitly fire the terminal disconnected event so the screen's
    ``_watch_disconnect`` wakes and runs ``session.close()`` —
    otherwise the ACP Connection + Sender + Dispatcher background
    tasks + the writer + the socket all leak on a completed sample
    until the user switches samples or the eval ends.
    """
    from inspect_ai.agent._acp.tui.client import _handle_session_ended

    state = SessionState()
    session = _make_session(state=state)
    session.session_id = "sid-1"

    assert session.disconnected.is_set() is False
    assert state.session_ended_received is False

    await _handle_session_ended(session, {"sessionId": "sid-1"})

    # All three transitions happened in order.
    assert state.session_ended_received is True
    assert state._complete is True
    assert session.disconnected.is_set() is True


@skip_if_trio
async def test_session_ended_handler_ignores_mismatched_session_id() -> None:
    """Identity guard: stray notifications for a different sessionId are no-ops."""
    from inspect_ai.agent._acp.tui.client import _handle_session_ended

    state = SessionState()
    session = _make_session(state=state)
    session.session_id = "sid-1"
    await _handle_session_ended(session, {"sessionId": "different-sid"})
    assert state.session_ended_received is False
    assert state._complete is False
    assert session.disconnected.is_set() is False


@skip_if_trio
async def test_run_receive_loop_closes_connection_on_clean_eof() -> None:
    """Regression: clean peer EOF must close the Connection.

    ``acp.Connection._receive_loop`` treats an empty ``readline()``
    as a normal return and does NOT itself reject pending outgoing
    futures. Without our finally-close, the handshake's
    ``await conn.send_request("initialize", ...)`` would hang
    forever on the pathological case where the server accepts the
    socket then closes before answering — the reconnect loop would
    get stuck in one iteration instead of backing off and retrying.

    Verifies ``_run_receive_loop`` calls ``conn.close()`` after
    ``main_loop`` returns cleanly.
    """
    from inspect_ai.agent._acp.tui.client import _run_receive_loop

    close_called = asyncio.Event()

    class _FakeConnection:
        async def main_loop(self) -> None:
            # Simulate clean EOF — return without exception.
            return

        async def close(self) -> None:
            close_called.set()

    await _run_receive_loop(_FakeConnection())  # type: ignore[arg-type]
    assert close_called.is_set()


@skip_if_trio
async def test_run_receive_loop_closes_connection_on_connection_error() -> None:
    """Regression: ConnectionError exit path also closes the Connection.

    Same invariant as the clean-EOF case, but via the raised-exception
    branch — must still close so pending futures unblock.
    """
    from inspect_ai.agent._acp.tui.client import _run_receive_loop

    close_called = asyncio.Event()

    class _FakeConnection:
        async def main_loop(self) -> None:
            raise ConnectionError("simulated peer reset")

        async def close(self) -> None:
            close_called.set()

    await _run_receive_loop(_FakeConnection())  # type: ignore[arg-type]
    assert close_called.is_set()


@skip_if_trio
async def test_run_receive_loop_closes_connection_on_cancellation() -> None:
    """Regression: own-cancellation path also closes the Connection.

    When the coordinator cancels the receive task during teardown /
    reconnect, the Connection must still be closed so its background
    Dispatcher / Sender tasks shut down. ``AttachedSession.close``
    and ``_establish_connection``'s error path both call
    ``conn.close()`` themselves; the finally close here is a no-op
    (idempotent via ``Connection._closed``) but defends against any
    path that cancels the receive task without explicit cleanup.
    """
    from inspect_ai.agent._acp.tui.client import _run_receive_loop

    close_called = asyncio.Event()
    in_main_loop = asyncio.Event()

    class _FakeConnection:
        async def main_loop(self) -> None:
            in_main_loop.set()
            await asyncio.sleep(3600)  # block until cancelled

        async def close(self) -> None:
            close_called.set()

    task = asyncio.create_task(_run_receive_loop(_FakeConnection()))  # type: ignore[arg-type]
    await in_main_loop.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert close_called.is_set()


@skip_if_trio
async def test_toast_cadence_does_not_fire_when_no_disconnected_at() -> None:
    """Defensive: no ``_disconnected_at`` → toast loop yields but is silent."""
    state = SessionState()
    clock = _FakeClock(start=0.0)
    notifications: list[tuple[str, str]] = []

    def _notify(msg: str, severity: str) -> None:
        notifications.append((msg, severity))

    async def _sleep(delay: float) -> None:
        clock.advance(delay)
        await asyncio.sleep(0)

    session = _make_session(
        state=state,
        notify=_notify,
        sleep=_sleep,
        clock=clock,
    )
    # Leave _disconnected_at unset — toast cadence should silently
    # continue (no AttributeError, no toast).
    task = asyncio.create_task(session._toast_cadence())
    for _ in range(30):
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert notifications == []


# ---------------------------------------------------------------------------
# Pilot tests — send-while-disconnected guard
# ---------------------------------------------------------------------------


class TestPilotReconnectUI:
    """Pilot-based tests need a running event loop + Textual app."""

    pytestmark = pytest.mark.slow

    @skip_if_trio
    @pytest.mark.anyio
    async def test_send_while_disconnected_toasts_and_preserves_draft(
        self, sample_rows: Any
    ) -> None:
        """Composer text survives a send attempt while transport is down."""
        from textual.widgets import TextArea

        from inspect_ai.agent._acp.tui.app import InspectAcpApp
        from inspect_ai.agent._acp.tui.session_screen import SessionScreen

        from .conftest import make_fake_client

        client = make_fake_client(sample_rows)
        app = InspectAcpApp(eval_id=None, server=None, client=client)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen._on_select(sample_rows[0])  # type: ignore[attr-defined]
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, SessionScreen):
                    break
            assert isinstance(app.screen, SessionScreen)
            screen = app.screen
            # Type into the composer; mark state disconnected; submit.
            # The composer is a ``ComposerTextArea`` (TextArea subclass)
            # — matches the sibling pilots in
            # ``test_queued_messages_pilot.py``. ``.text`` is the
            # TextArea analogue of Input's ``.value``.
            composer = screen.query_one("#composer", TextArea)
            composer.text = "hello"
            screen._state.mark_disconnected()
            await pilot.pause()
            await screen.action_submit()
            await pilot.pause()
            # Draft preserved.
            assert composer.text == "hello"
            # No request reached the fake connection. The fake's
            # _FakeConnection exposes ``requests``; the real
            # ``acp.Connection`` doesn't.
            conn: Any = screen._session.connection
            assert conn.requests == []
