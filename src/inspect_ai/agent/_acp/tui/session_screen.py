"""Session screen for the ``inspect acp`` TUI (Phase 2).

Layout:

  - :class:`SessionHeaderWidget` — single-row app title + meta
    identifiers (task / sample / epoch / agent / tokens) + connection
    indicator.
  - :class:`TranscriptWidget` — scrollable conversation pane.
  - Composer placeholder (disabled — Phase 3 wires it).
  - Textual ``Footer`` for keymap hints.

Read-only: composer disabled, ``Esc`` doesn't interrupt yet. Phase 3
adds both.

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

    # ``priority=True`` so the binding fires regardless of focused
    # widget — once the Phase 3 composer goes live we still want ^S to
    # leave the session even if the Input has focus.
    BINDINGS = [
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
    #composer {
        height: 3;
        margin: 0 2 1 2;
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
                placeholder="composer (Phase 3 enables this)",
                id="composer",
                disabled=True,
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
