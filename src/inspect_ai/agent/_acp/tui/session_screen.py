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
from textual.containers import Vertical
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
        state: SessionState | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._on_disconnect = on_disconnect
        self._watch_task: asyncio.Task[None] | None = None
        self._state = state if state is not None else SessionState()
        self._unsubscribe: Callable[[], None] | None = None

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
        except Exception:
            return
        header.set_usage(self._state.usage)
        transcript.refresh_from(self._state)

    def _tick(self) -> None:
        # In-flight tool durations + the assistant chip spinner have no
        # state mutation that fires ``subscribe``, so we nudge them
        # here on a timer.
        try:
            self.query_one(TranscriptWidget).tick_inflight_durations()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Disconnect watch
    # ------------------------------------------------------------------

    async def _watch_disconnect(self) -> None:
        try:
            while not self._session.disconnected.is_set():
                if self._session.writer.is_closing():
                    break
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

        if self._session.disconnected.is_set():
            return

        await self._session.close()
        try:
            self.query_one(SessionHeaderWidget).set_connected(False)
            self.app.notify("disconnected from server", severity="warning")
        except Exception:
            pass
        self._on_disconnect()
