"""Session screen for the ``inspect acp`` TUI (Phase 2).

Wires :class:`SessionState` into the conversation pane: meta row,
status row (pill + chips), scrollable transcript, composer placeholder,
footer. Read-only — composer is disabled and ``Esc`` doesn't interrupt
yet; Phase 3 wires both.

The status pill's quiescence transition (``Generating → Awaiting``) is
time-driven by :attr:`SessionState.status`. A periodic ``set_interval``
timer calls ``_apply_state`` so the pill flips after the last chunk
even when no notification arrives to fire ``subscribe``.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from ._client import AttachedSession
from ._state import SessionState
from ._widgets import StatusRowWidget, TranscriptWidget

_STATUS_TICK_SECONDS = 0.5
"""How often the pill state is re-derived.

Drives the GENERATING → AWAITING_INPUT transition (which is time-based
and isn't fired by any notification). Sub-second so the transition
feels prompt; not so fast that idle CPU is wasted.
"""


class SessionScreen(Screen[None]):
    """Phase 2 attached-session view."""

    DEFAULT_CSS = """
    SessionScreen { layout: vertical; }
    #meta-row { padding: 1 2; height: auto; }
    #meta-row .meta { width: 1fr; }
    #meta-row .conn { width: auto; padding-left: 2; }
    #meta-row .conn.up { color: $success; }
    #meta-row .conn.down { color: $error; }
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
        yield Header(show_clock=False)
        with Vertical():
            with Horizontal(id="meta-row"):
                yield Static(self._meta_text(), classes="meta", id="meta-text")
                yield Static("● connected", classes="conn up", id="conn-indicator")
            yield StatusRowWidget()
            yield TranscriptWidget()
            yield Input(
                placeholder="composer (Phase 3 enables this)",
                id="composer",
                disabled=True,
            )
        yield Footer()

    def _meta_text(self) -> str:
        row = self._session.row
        agent = row.agent_name or "—"
        return (
            f"inspect acp · {row.eval_id} · {row.task} "
            f"· {row.sample_id}/{row.epoch} · agent: {agent}"
        )

    async def on_mount(self) -> None:
        self._apply_state()
        # Subscribe AFTER the initial paint so the first state-driven
        # refresh runs through the same _apply_state path as later
        # change notifications.
        self._unsubscribe = self._state.subscribe(self._on_state_change)
        # Time-driven pill refresh — see _STATUS_TICK_SECONDS comment.
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
            status_row = self.query_one(StatusRowWidget)
            transcript = self.query_one(TranscriptWidget)
        except Exception:
            return
        status_row.refresh_from(self._state)
        transcript.refresh_from(self._state)

    def _tick(self) -> None:
        # Two time-driven things need a periodic nudge: the pill state
        # (quiescence flip from GENERATING → AWAITING_INPUT) and the
        # in-flight tool-call duration counters. Neither has a state
        # mutation that fires `subscribe`, so the screen does it on a
        # timer.
        try:
            self.query_one(StatusRowWidget).refresh_from(self._state)
        except Exception:
            pass
        try:
            self.query_one(TranscriptWidget).tick_inflight_durations()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Disconnect watch (unchanged from Phase 1)
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
            indicator = self.query_one("#conn-indicator", Static)
            indicator.update("○ disconnected")
            indicator.remove_class("up")
            indicator.add_class("down")
            self.app.notify("disconnected from server", severity="warning")
        except Exception:
            pass
        self._on_disconnect()
