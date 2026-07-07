"""Textual harness tests for the inline cancel-sample card.

Mirrors ``test_approval_card.py``: mounts the card in a minimal
:class:`App`, drives button clicks, asserts that the card fires
the ``inspect/cancel_sample`` RPC for Score / Error and resolves
the pending slot. Back is the no-RPC no-op.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from test_helpers.utils import skip_if_trio
from textual.app import App, ComposeResult
from textual.widgets import Button

from inspect_ai.agent._acp.inspect_ext import INSPECT_CANCEL_SAMPLE_METHOD
from inspect_ai.agent._acp.tui.state import PendingCancel, SessionState
from inspect_ai.agent._acp.tui.widgets.cancel_card import (
    _BUTTON_ID_PREFIX,
    _CancelCard,
)


class _FakeConnection:
    """Records ``send_request`` calls; resolves to whatever the test sets."""

    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._result = result
        self._exc = exc

    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        if self._exc is not None:
            raise self._exc
        return self._result


def _state() -> SessionState:
    """Build a real SessionState — the card mutates ``pending_cancel``."""
    return SessionState()


def _pending(
    *,
    fails_on_error: bool = False,
    connection: Any | None = None,
    session_id: str = "sess-1",
) -> tuple[PendingCancel, _FakeConnection]:
    conn = connection if connection is not None else _FakeConnection()
    return (
        PendingCancel(
            fails_on_error=fails_on_error,
            connection=conn,
            session_id=session_id,
        ),
        conn,
    )


class _CardApp(App[None]):
    """Minimal host that owns a SessionState and mounts the cancel card."""

    def __init__(self, pending: PendingCancel, state: SessionState) -> None:
        super().__init__()
        self._pending = pending
        self._state = state
        # Mirror the screen's contract: state holds the pending while
        # the card is mounted; the card clears it on resolution.
        self._state.consume_cancel_request(pending)

    def compose(self) -> ComposeResult:
        yield _CancelCard(self._pending, self._state)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_card_renders_prompt_header() -> None:
    """Header reads ``"Cancel the sample?"``."""
    from textual.widgets import Static

    pending, _ = _pending()
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        header = pilot.app.query_one(".request-header", Static)
        assert "Cancel" in str(header.render())


@skip_if_trio
@pytest.mark.anyio
async def test_card_mounts_three_buttons_when_fails_on_error_false() -> None:
    """``fails_on_error=False`` → Score / Error / Back are all offered."""
    pending, _ = _pending(fails_on_error=False)
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        buttons = list(pilot.app.query("#request-actions Button"))
        ids = [b.id for b in buttons]
        assert ids == [
            f"{_BUTTON_ID_PREFIX}score",
            f"{_BUTTON_ID_PREFIX}error",
            f"{_BUTTON_ID_PREFIX}back",
        ]


@skip_if_trio
@pytest.mark.anyio
async def test_card_omits_error_button_when_fails_on_error_true() -> None:
    """``fails_on_error=True`` → only Score and Back are offered.

    Operator-triggered error is moot when the sample is already
    configured to fail on errors (would race with the auto-fail).
    """
    pending, _ = _pending(fails_on_error=True)
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        ids = [b.id for b in pilot.app.query("#request-actions Button")]
        assert ids == [
            f"{_BUTTON_ID_PREFIX}score",
            f"{_BUTTON_ID_PREFIX}back",
        ]


@skip_if_trio
@pytest.mark.anyio
async def test_buttons_carry_kind_class_for_colour_vocabulary() -> None:
    """Score → kind-score (success); Error → kind-error (warning); Back → kind-back (dim)."""
    pending, _ = _pending(fails_on_error=False)
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        score = pilot.app.query_one(f"#{_BUTTON_ID_PREFIX}score", Button)
        error = pilot.app.query_one(f"#{_BUTTON_ID_PREFIX}error", Button)
        back = pilot.app.query_one(f"#{_BUTTON_ID_PREFIX}back", Button)
        assert "kind-score" in score.classes
        assert "kind-error" in error.classes
        assert "kind-back" in back.classes


# ---------------------------------------------------------------------------
# Back → no RPC, clear pending
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_back_clears_pending_without_firing_rpc() -> None:
    """``Back`` clears ``state.pending_cancel`` and does NOT fire the RPC."""
    pending, conn = _pending()
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        await pilot.click(f"#{_BUTTON_ID_PREFIX}back")
        await pilot.pause()
    assert state.pending_cancel is None
    assert conn.calls == []


# ---------------------------------------------------------------------------
# Score / Error → RPC + mark_sample_cancelling + clear pending
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_score_fires_cancel_rpc_with_correct_payload() -> None:
    """``Score`` sends ``inspect/cancel_sample`` with action=score."""
    pending, conn = _pending(session_id="sess-xyz")
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        await pilot.click(f"#{_BUTTON_ID_PREFIX}score")
        # Worker runs on a later tick — pause until quiescence.
        for _ in range(5):
            await pilot.pause()
            if conn.calls:
                break
    assert len(conn.calls) == 1
    method, params = conn.calls[0]
    assert method == INSPECT_CANCEL_SAMPLE_METHOD
    assert params == {"sessionId": "sess-xyz", "action": "score"}
    assert state.pending_cancel is None


@skip_if_trio
@pytest.mark.anyio
async def test_error_fires_cancel_rpc_with_action_error() -> None:
    """``Error`` sends ``inspect/cancel_sample`` with action=error."""
    pending, conn = _pending(fails_on_error=False)
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        await pilot.click(f"#{_BUTTON_ID_PREFIX}error")
        for _ in range(5):
            await pilot.pause()
            if conn.calls:
                break
    assert len(conn.calls) == 1
    assert conn.calls[0][1]["action"] == "error"


@skip_if_trio
@pytest.mark.anyio
async def test_score_marks_sample_cancelling_on_success() -> None:
    """RPC success → ``state._cancelling`` flips True (drives lifecycle pill)."""
    pending, conn = _pending()
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        await pilot.click(f"#{_BUTTON_ID_PREFIX}score")
        for _ in range(5):
            await pilot.pause()
            if not state.pending_cancel:
                break
    # ``_cancelling`` is the sticky flag the lifecycle pill consults.
    assert state._cancelling is True


@skip_if_trio
@pytest.mark.anyio
async def test_rpc_failure_clears_pending_and_does_not_mark_cancelling() -> None:
    """RPC raise → operator gets a toast, pending clears, ``_cancelling`` stays False.

    Local state is left honest — the sample didn't actually cancel
    so we don't flip the lifecycle flag.
    """
    failing = _FakeConnection(exc=RuntimeError("server gone"))
    pending, _ = _pending(connection=failing)
    state = _state()

    # Capture toast notifications.
    notify_calls: list[tuple[str, str | None]] = []
    async with _CardApp(pending, state).run_test() as pilot:
        original_notify = pilot.app.notify

        def _record_notify(
            message: str, *, severity: str | None = None, **_: Any
        ) -> None:
            notify_calls.append((message, severity))
            # Don't call original_notify — the harness can't render toasts.

        pilot.app.notify = _record_notify  # type: ignore[method-assign]
        del original_notify
        await pilot.click(f"#{_BUTTON_ID_PREFIX}score")
        for _ in range(5):
            await pilot.pause()
            if not state.pending_cancel:
                break
    assert state.pending_cancel is None
    assert state._cancelling is False
    assert notify_calls and "cancel failed" in notify_calls[0][0]


@skip_if_trio
@pytest.mark.anyio
async def test_double_click_score_only_fires_rpc_once() -> None:
    """Idempotence: rapid Enter mash doesn't double-fire the RPC.

    The card's ``_resolved`` guard catches re-presses that land
    before the unmount races.
    """
    pending, conn = _pending()
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        # Click twice in a row before yielding.
        await pilot.click(f"#{_BUTTON_ID_PREFIX}score")
        await pilot.click(f"#{_BUTTON_ID_PREFIX}score")
        for _ in range(5):
            await pilot.pause()
    # Only one RPC despite two clicks.
    assert len(conn.calls) == 1


class _SlowConnection:
    """Connection whose ``send_request`` parks until ``release`` is set.

    Lets tests simulate a slow ``inspect/cancel_sample`` round-trip and
    exercise what happens to ``pending_cancel`` while the RPC is mid-
    flight. The card's ``_resolved`` guard plus the ``Cancelling…``
    presentation are supposed to block Back / Esc / repeat-Score from
    clearing the pending underneath the worker — see
    ``test_back_after_score_in_flight_is_a_noop`` below.
    """

    def __init__(self) -> None:
        import anyio

        self.release = anyio.Event()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, params))
        await self.release.wait()
        return None


@skip_if_trio
@pytest.mark.anyio
async def test_back_after_score_in_flight_does_not_clear_pending() -> None:
    """Race regression: Back press while cancel RPC is in flight is a no-op.

    Pinned scenario: operator picks Score → ``_CancelCard`` sets
    ``_resolved=True`` and spawns the worker that calls
    ``inspect/cancel_sample``. The worker is currently parked
    inside ``send_request`` (slow server, network blip, queued
    behind another request). Before the worker can finish, the
    operator changes their mind and clicks Back — or presses Esc,
    which the session screen routes through ``action_interrupt``
    into the same ``choose("back")`` path.

    Old behaviour: Back unconditionally called ``resolve_cancel``,
    clearing ``pending_cancel`` and unmounting the card while the
    RPC was still in flight. The UI then read as "keep running"
    even though the cancel could still succeed.

    New behaviour: once ``_resolved`` flips True, ``choose``
    short-circuits ALL further choices (including Back), the
    action buttons are disabled, and the header reads
    ``Cancelling…``. Pending stays parked until the worker
    finishes.
    """
    from textual.widgets import Static

    slow = _SlowConnection()
    pending, _ = _pending(connection=slow)
    state = _state()
    async with _CardApp(pending, state).run_test() as pilot:
        # Score → fires worker; worker parks inside ``send_request``.
        await pilot.click(f"#{_BUTTON_ID_PREFIX}score")
        for _ in range(5):
            await pilot.pause()
            if slow.calls:
                break
        assert len(slow.calls) == 1, "score press did not fire send_request"

        # Card flipped into "Cancelling…" with disabled buttons and
        # pending still parked (worker hasn't completed yet).
        card = pilot.app.query_one(_CancelCard)
        assert card._resolved is True
        assert state.pending_cancel is pending
        header = pilot.app.query_one(".request-header", Static)
        assert "Cancelling" in str(header.render())
        for button in pilot.app.query("#request-actions Button"):
            assert button.disabled is True, (
                f"expected button {button.id} disabled while cancel in flight"
            )

        # Back press lands on the disabled button; the card's
        # ``choose("back")`` is short-circuited by the ``_resolved``
        # guard. ``await pilot.click`` on a disabled button is a
        # no-op in Textual, so call ``choose`` directly to exercise
        # the bare-letter / message dispatch path that DOES still
        # reach the method.
        card.choose("back")
        await pilot.pause()
        assert state.pending_cancel is pending, (
            "Back must not clear pending while cancel RPC is in flight"
        )

        # A re-Score also no-ops (idempotence still holds via the
        # same ``_resolved`` short-circuit).
        card.choose("score")
        await pilot.pause()
        assert len(slow.calls) == 1, "re-Score must not fire a second RPC"

        # Now let the RPC settle — the worker's success path clears
        # pending and flips ``_cancelling`` on the state.
        slow.release.set()
        for _ in range(10):
            await pilot.pause()
            if not state.pending_cancel:
                break
        assert state.pending_cancel is None
        assert state._cancelling is True


# ---------------------------------------------------------------------------
# State-helper smoke tests (consume / resolve / _clear_pending_cancel)
# ---------------------------------------------------------------------------


def test_consume_cancel_request_is_idempotent_on_repeat() -> None:
    """``consume_cancel_request`` on an already-pending state is a no-op.

    The second call must NOT stomp the original pending — the screen
    treats repeat ``^N`` as a "scroll back" gesture, not a re-prompt.
    """
    state = _state()
    pending1 = PendingCancel(
        fails_on_error=False, connection=MagicMock(), session_id="s1"
    )
    pending2 = PendingCancel(
        fails_on_error=False, connection=MagicMock(), session_id="s2"
    )
    state.consume_cancel_request(pending1)
    state.consume_cancel_request(pending2)
    assert state.pending_cancel is pending1


def test_resolve_cancel_clears_pending() -> None:
    """``resolve_cancel`` clears the slot and is idempotent."""
    state = _state()
    pending = PendingCancel(
        fails_on_error=False, connection=MagicMock(), session_id="s1"
    )
    state.consume_cancel_request(pending)
    assert state.pending_cancel is pending
    state.resolve_cancel()
    assert state.pending_cancel is None
    # Idempotent: second resolve is a no-op (no exception).
    state.resolve_cancel()
    assert state.pending_cancel is None
