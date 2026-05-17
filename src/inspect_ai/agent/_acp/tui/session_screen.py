"""Session screen for the ``inspect acp`` TUI.

Layout:

  - :class:`SessionHeaderWidget` — single-row app title + meta
    identifiers (task / sample / epoch / agent / tokens) + connection
    indicator.
  - :class:`TranscriptWidget` — scrollable conversation pane.
  - Composer ``Input`` — user types prompts; ``↵`` sends, ``Esc``
    interrupts (or clears the draft when one is present).
  - Textual ``Footer`` for keymap hints.

A periodic ``set_interval`` timer calls ``_tick`` so in-flight tool
duration counters and the assistant chip spinner keep ticking even
between notifications.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Input

from .client import AttachedSession
from .state import SessionState
from .widgets import (
    SessionHeaderWidget,
    TranscriptWidget,
)

_STATUS_TICK_SECONDS = 0.5
"""How often time-driven UI bits get nudged.

In-flight tool durations + the assistant chip spinner don't have
state mutations that fire ``subscribe``, so the screen ticks them on
this interval. Sub-second so the motion feels responsive; not so
fast that idle CPU is wasted.
"""


class SessionScreen(Screen[None]):
    """Phase 2 attached-session view."""

    # ``priority=True`` on every binding so they fire regardless of
    # focused widget — the composer ``Input`` would otherwise eat
    # ``enter`` (firing its own ``Input.Submitted``) and the screen
    # action never runs. Same reasoning for ``escape``; same for ^S so
    # the user can always leave the session.
    BINDINGS = [
        Binding("enter", "submit", "submit", show=True, key_display="↵", priority=True),
        Binding("escape", "interrupt", "interrupt", show=True, priority=True),
        Binding(
            "ctrl+s",
            "switch_sample",
            "switch sample",
            show=True,
            priority=True,
        ),
    ]

    DEFAULT_CSS = """
    SessionScreen { layout: vertical; }
    /* margin-top: 1 so the composer doesn't sit flush against the
     * last transcript item — gives the input visual breathing room
     * from the conversation it's appending to. */
    #composer {
        height: 3;
        margin: 1 2 1 2;
        border: tall $primary 30%;
    }
    """

    def __init__(
        self,
        *,
        session: AttachedSession,
        on_disconnect: Callable[[], None],
        state: SessionState,
    ) -> None:
        super().__init__()
        self._session = session
        self._on_disconnect = on_disconnect
        self._watch_task: asyncio.Task[None] | None = None
        self._state = state
        self._unsubscribe: Callable[[], None] | None = None
        # Set by ``action_switch_sample`` so the disconnect watcher can
        # tell a user-initiated pop from a peer-side EOF and skip the
        # otherwise-misleading "disconnected from server" toast.
        self._user_initiated_close = False

    @property
    def state(self) -> SessionState:
        return self._state

    def compose(self) -> ComposeResult:
        with Vertical():
            yield SessionHeaderWidget(self._session.row)
            yield TranscriptWidget()
            yield Input(
                placeholder="type a message for the agent…",
                id="composer",
            )
        yield Footer()

    async def on_mount(self) -> None:
        self._apply_state()
        # Subscribe AFTER the initial paint so the first state-driven
        # refresh runs through the same _apply_state path as later
        # change notifications.
        self._unsubscribe = self._state.subscribe(self._on_state_change)
        # Time-driven status refresh — see _STATUS_TICK_SECONDS comment.
        self.set_interval(_STATUS_TICK_SECONDS, self._tick)
        self._watch_task = asyncio.create_task(self._watch_disconnect())

    async def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()
        await self._session.close()

    # ------------------------------------------------------------------
    # State change handling
    # ------------------------------------------------------------------

    def _on_state_change(self) -> None:
        # Subscribers fire from acp.Connection's reader task — same
        # asyncio loop as Textual, so no thread hop needed.
        self._apply_state()

    def _apply_state(self) -> None:
        try:
            header = self.query_one(SessionHeaderWidget)
            transcript = self.query_one(TranscriptWidget)
        except NoMatches:
            return
        header.set_usage(self._state.usage)
        transcript.refresh_from(self._state)

    def _tick(self) -> None:
        # In-flight tool durations + the assistant chip spinner have no
        # state mutation that fires ``subscribe``, so we nudge them
        # here on a timer.
        try:
            self.query_one(TranscriptWidget).tick_inflight_durations()
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Disconnect watch
    # ------------------------------------------------------------------

    async def _watch_disconnect(self) -> None:
        """Notify + pop back to the picker as soon as the peer goes away.

        The client's receive-task sets ``disconnected`` on EOF / read
        error / explicit close — so this just blocks on the event and
        reacts. The previous polling loop was a workaround for the
        absence of that wiring and added a ~500ms quantum to the
        user-visible recovery.
        """
        try:
            await self._session.disconnected.wait()
        except asyncio.CancelledError:
            return
        # User-initiated ^S switch closes the session itself, which
        # fires ``disconnected``. The action handler has already kicked
        # off the pop; the toast would be misleading ("disconnected"
        # vs "you asked to switch") so swallow it.
        if self._user_initiated_close:
            return
        try:
            self.query_one(SessionHeaderWidget).set_connected(False)
            self.app.notify("disconnected from server", severity="warning")
        except NoMatches:
            pass
        self._on_disconnect()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_switch_sample(self) -> None:
        """Disconnect from the current session and return to the picker."""
        self._user_initiated_close = True
        self._on_disconnect()

    async def action_submit(self) -> None:
        """Send the composer's text to the agent as a ``session/prompt``.

        Empty composer is a no-op so a stray ``↵`` doesn't fire a
        meaningless request. Errors from the server (connection dead,
        session vanished) surface as a toast — the user still owns the
        text, since we only clear after the request returns.
        """
        composer = self._composer_or_none()
        if composer is None:
            return
        text = composer.value.strip()
        if not text:
            return
        connection = self._session.connection
        if connection is None:
            self.app.notify("not connected", severity="warning")
            return
        try:
            await connection.send_request(
                "session/prompt",
                {
                    "sessionId": self._session.session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            )
        except Exception as exc:
            self.app.notify(f"failed to send: {exc}", severity="error")
            return
        composer.value = ""

    async def action_interrupt(self) -> None:
        """Clear the composer draft, or interrupt the running turn.

        Mirrors the design-doc keymap: ``Esc`` clears the draft when
        one is present (so a typo is easy to undo). With an empty
        composer, sends ``session/cancel`` ONLY while the agent is
        actually working — gated on
        :attr:`SessionState.has_active_work` (pending model events OR
        in-flight tools) rather than the looser display
        :attr:`StatusState.GENERATING`, which also fires for the
        2-second quiescence tail after a normal response. Cancelling
        during that tail would manufacture a misleading
        ``between_turns`` ``InterruptEvent`` on the server.
        """
        composer = self._composer_or_none()
        if composer is not None and composer.value:
            composer.value = ""
            return
        if not self._state.has_active_work:
            return
        connection = self._session.connection
        if connection is None:
            return
        # Clear local in-flight signals BEFORE sending so the spinner /
        # status pill react instantly rather than waiting for the
        # server's cancel propagation to round-trip back to us.
        self._state.mark_interrupted()
        try:
            await connection.send_notification(
                "session/cancel",
                {"sessionId": self._session.session_id},
            )
        except Exception as exc:
            self.app.notify(f"failed to interrupt: {exc}", severity="error")

    def _composer_or_none(self) -> Input | None:
        """The composer Input, or None if it isn't mounted (defensive)."""
        try:
            return self.query_one("#composer", Input)
        except NoMatches:
            return None
