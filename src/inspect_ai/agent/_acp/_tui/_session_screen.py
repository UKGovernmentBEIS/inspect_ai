"""Session screen for the ``inspect acp`` TUI (Phase 1 skeleton).

Renders only the meta row + connection indicator. The transcript,
composer, status pill, and event widgets land in Phase 2+. The screen
exists in Phase 1 so we can prove the attach flow end-to-end and so
the meta-row data shape (which depends on protocol extensions #1 and
#5) is exercised.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ._client import AttachedSession


class SessionScreen(Screen[None]):
    """Minimal attached-session view; meta row + connected indicator."""

    DEFAULT_CSS = """
    SessionScreen { layout: vertical; }
    #meta-row { padding: 1 2; height: auto; }
    #meta-row .meta { width: 1fr; }
    #meta-row .conn { width: auto; padding-left: 2; }
    #meta-row .conn.up { color: $success; }
    #meta-row .conn.down { color: $error; }
    #body { padding: 2 4; color: $text-muted; height: 1fr; }
    """

    def __init__(
        self,
        *,
        session: AttachedSession,
        on_disconnect: Callable[[], None],
    ) -> None:
        super().__init__()
        self._session = session
        self._on_disconnect = on_disconnect
        self._watch_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical():
            with Horizontal(id="meta-row"):
                yield Static(self._meta_text(), classes="meta", id="meta-text")
                yield Static("● connected", classes="conn up", id="conn-indicator")
            yield Static(
                "Phase 1: transport + picker only. Transcript rendering "
                "lands in Phase 2.",
                id="body",
            )
        yield Footer()

    def _meta_text(self) -> str:
        row = self._session.row
        agent = row.agent_name or "—"
        # Drop the field-name prefaces for the eval/task/sample/epoch
        # fields — context makes them obvious. Keep ``agent:`` because
        # it's the one field whose value (e.g. "react") isn't
        # self-identifying.
        return (
            f"inspect acp · {row.eval_id} · {row.task} "
            f"· {row.sample_id}/{row.epoch} · agent: {agent}"
        )

    async def on_mount(self) -> None:
        # Watch for peer disconnect. The acp Connection's main_loop
        # finishes when the reader hits EOF; we don't drive it
        # ourselves (listening=True), so monitor the underlying
        # writer instead.
        self._watch_task = asyncio.create_task(self._watch_disconnect())

    async def on_unmount(self) -> None:
        if self._watch_task is not None and not self._watch_task.done():
            self._watch_task.cancel()
        await self._session.close()

    async def _watch_disconnect(self) -> None:
        try:
            while not self._session.disconnected.is_set():
                # asyncio.StreamWriter.is_closing() flips when the
                # peer closes the socket. Cheap to poll.
                if self._session.writer.is_closing():
                    break
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

        if self._session.disconnected.is_set():
            return

        await self._session.close()
        # Flip the indicator before unwinding; the on_disconnect
        # callback typically pops the screen so the visual change is
        # transient, but it's the correct state if the screen lingers.
        try:
            indicator = self.query_one("#conn-indicator", Static)
            indicator.update("○ disconnected")
            indicator.remove_class("up")
            indicator.add_class("down")
            self.app.notify("disconnected from server", severity="warning")
        except Exception:
            pass
        self._on_disconnect()
