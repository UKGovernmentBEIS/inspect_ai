"""Top-level Textual app for ``inspect acp``.

Wires discovery + enumeration on mount, hosts the picker / session
screens, owns the single ``AttachedSession`` when one is bound.

App-level bindings: only ``ctrl+c`` (the design-doc reserved app-quit
binding). Bare letters like ``q`` are intentionally NOT bound — they
need to remain typeable in the Phase 3 composer.
"""

from __future__ import annotations

import sys
from typing import Any

from textual.app import App
from textual.binding import Binding

from inspect_ai.agent._acp.discovery import (
    TargetAddress,
    TargetResolutionError,
    list_discovered_evals,
    parse_host_port,
)

from . import client as _client
from .client import AttachedSession, SessionRow
from .picker_screen import PickerScreen
from .session_screen import SessionScreen
from .state import SessionState


class InspectAcpApp(App[None]):
    """The ``inspect acp`` Textual application."""

    BINDINGS = [
        # ^X quits the app. Bare letters MUST NOT be added here —
        # they would collide with the Phase 3 composer.
        #
        # Choice rationale: ^Q collides with VS Code's "Close Window"
        # command (annoying when the TUI runs in the integrated
        # terminal). The base App still inherits a default ^Q→quit
        # binding which we can't easily remove — but our explicit
        # ^X→quit takes precedence for actual key handling, and we
        # override ``action_help_quit`` (below) so the ^C notification
        # also shows ^X.
        Binding("ctrl+x", "quit", "quit", show=True, priority=True),
    ]

    # Suppress the default ``ctrl+p`` command-palette binding — its
    # footer hint adds noise and the palette has no commands of our
    # own registered yet. Phase 3+ may revisit this when slash
    # commands need a discoverability surface.
    ENABLE_COMMAND_PALETTE = False

    TITLE = "inspect acp"

    # Bold-blue title styling to match the inspect_ai task display
    # banner (``$accent`` is the standard primary-blue token in
    # Textual's default theme — same colour family the user sees in
    # the eval task header).
    CSS = """
    HeaderTitle {
        color: $accent;
        text-style: bold;
    }
    """

    def __init__(
        self,
        *,
        eval_id: str | None,
        server: str | None,
        client: Any = None,
    ) -> None:
        """Construct the app.

        ``client`` is an injection point for tests — a module-like
        object exposing ``enumerate_sessions`` and ``attach_session``
        with the same signatures as :mod:`.client`. Defaults to the
        real module. Typed ``Any`` because the injection is duck-
        typed; the module is passed as an object rather than a
        Protocol-shaped value.
        """
        super().__init__()
        self._eval_id = eval_id
        self._server = server
        self._client: Any = client if client is not None else _client
        self._attached: AttachedSession | None = None
        # When the user passed ``--server <addr>``, surface the address
        # in the title bar so it's obvious which remote the TUI is
        # pointed at. The default ``inspect acp`` covers the local-
        # discovery case where there's nothing useful to add.
        if server is not None:
            self.title = f"inspect acp · {server}"

    async def on_mount(self) -> None:
        try:
            self._resolve_addresses()
        except TargetResolutionError as exc:
            # An explicit --server that fails to parse is a CLI-level
            # error; surface to stderr + exit (we're past click's
            # parse phase but still pre-render).
            print(str(exc), file=sys.stderr, flush=True)
            self.exit(return_code=2)
            return

        rows = await self._enumerate()
        self._push_picker(rows)

    async def _enumerate(self) -> list[SessionRow]:
        """Resolve addresses + enumerate sessions; safe to call repeatedly.

        Returns the empty list on any failure rather than raising —
        the picker uses this for periodic rescan and shouldn't crash
        if a discovered eval temporarily fails to respond.
        """
        try:
            addresses = self._resolve_addresses()
        except TargetResolutionError:
            return []
        try:
            rows: list[SessionRow] = await self._client.enumerate_sessions(
                addresses,
                eval_id_filter=self._eval_id,
            )
            return rows
        except Exception as exc:
            print(
                f"inspect acp: enumeration failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return []

    def action_help_quit(self) -> None:
        """Override Textual's ^C → "Press ^Q to quit" prompt.

        The base ``App.action_help_quit`` walks ``active_bindings``
        and emits the first ``quit``-action key it finds — which is
        the inherited default ^Q, not our explicit ^X. Override here
        so the prompt names the binding we actually surface.
        """
        self.notify(
            "Press [b]ctrl+x[/b] to quit the app",
            title="Do you want to quit?",
        )

    def _resolve_addresses(self) -> list[tuple[str, TargetAddress]]:
        """Build the (eval_id, target) pairs to enumerate.

        ``--server`` wins: single synthetic-id address, no discovery.
        Otherwise enumerate the discovery dir; the ``--eval-id`` filter
        is applied later (after rows are collected) so a typo doesn't
        skip the eval that just registered.
        """
        if self._server is not None:
            target = _parse_target(self._server)
            # Use the address's describe() as a synthetic eval id —
            # it's only used to label the picker row when the remote
            # eval's true id isn't yet known here. (The server's
            # discovery file would carry the real id, but --server
            # bypasses discovery by design.)
            return [(target.describe(), target)]

        discovered = list_discovered_evals()
        return [(e.eval_id, e.target) for e in discovered]

    def _push_picker(self, rows: list[SessionRow]) -> None:
        self.push_screen(
            PickerScreen(
                rows=rows,
                server_override=self._server,
                on_select=self._on_picker_select,
                rescan=self._enumerate,
            )
        )

    def _on_picker_select(self, row: SessionRow) -> None:
        # Defer to a worker so the picker callback returns promptly;
        # the attach round-trip involves a real TCP/UNIX connect +
        # initialize + load_session.
        self.run_worker(self._attach_and_show(row), exclusive=True)

    async def _attach_and_show(self, row: SessionRow) -> None:
        state = SessionState()
        try:
            # Pass state.consume directly: the client's notification
            # route fires it from the reader task, which runs on the
            # same asyncio loop as Textual so widget refreshes happen
            # synchronously without a thread hop.
            session = await self._client.attach_session(
                row, on_session_update=state.consume
            )
        except Exception as exc:
            self.notify(f"failed to attach: {exc}", severity="error")
            return
        self._attached = session
        self.push_screen(
            SessionScreen(
                session=session,
                on_disconnect=self._on_session_disconnect,
                state=state,
            )
        )

    def _on_session_disconnect(self) -> None:
        # Pop back to the picker; Phase 5 will replace this with
        # reconnect-with-backoff logic.
        self._attached = None
        # Use call_later so the pop happens off the disconnect's
        # callback stack.
        self.call_later(self._safe_pop_screen)

    def _safe_pop_screen(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()


def _parse_target(value: str) -> TargetAddress:
    """Parse a ``--server`` string into a :class:`TargetAddress`.

    Same parsing rules as :func:`resolve_target`'s ``server`` branch,
    duplicated here so the TUI can build its address list without
    exercising the discovery-dir fallback path.
    """
    from pathlib import Path

    try:
        host_port = parse_host_port(value)
    except ValueError as exc:
        raise TargetResolutionError(f"invalid --server value {value!r}: {exc}") from exc
    if host_port is not None:
        host, port = host_port
        return TargetAddress(host=host, port=port)
    return TargetAddress(socket_path=Path(value))


async def run_tui(*, eval_id: str | None, server: str | None) -> None:
    """Entry point called by the CLI when ``--stdio`` is omitted."""
    app = InspectAcpApp(eval_id=eval_id, server=server)
    await app.run_async()
