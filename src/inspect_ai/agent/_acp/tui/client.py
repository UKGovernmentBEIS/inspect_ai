"""ACP client helpers for the ``inspect acp`` TUI.

Two responsibilities, no Textual imports:

- :func:`enumerate_sessions` fans out across discovered evals (or one
  ``--server`` address), calls ``initialize`` + ``inspect/list_sessions``
  on each, aggregates the per-eval target lists into a flat picker row
  set, and closes its connections.
- :func:`attach_session` opens a long-lived connection bound to one
  target via ``session/load``; the returned :class:`AttachedSession`
  holds the live ``acp.Connection`` and signals when the peer EOFs.

Both layers are asyncio-anchored (same reason as the rest of the ACP
code — the ``acp`` library uses asyncio streams + futures throughout).
See ``design/acp/agent-acp.md`` "asyncio / anyio boundary".
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Any, Callable

from acp import PROTOCOL_VERSION
from acp.connection import Connection
from acp.router import MessageRouter, Route
from acp.schema import SessionNotification

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import INSPECT_LIST_SESSIONS_METHOD

CLIENT_INFO = {"name": "inspect-acp-tui", "version": "1"}
"""Sent in ``initialize`` so the server can tailor capability negotiation
(plan rendering, raw events). The TUI is Inspect-aware; future phases
may opt into ``inspect.raw_events`` via ``clientCapabilities._meta``."""


@dataclass(frozen=True)
class SessionRow:
    """One row in the picker table.

    Carries both the user-visible identifiers and the connection
    address — the picker needs to remember which eval each session
    belongs to so it can open a fresh attach connection without
    redoing discovery.
    """

    eval_id: str
    """Owning eval id (matches the discovery file)."""

    session_id: str
    """ACP session uuid; passed to ``session/load`` on attach."""

    task: str
    sample_id: str
    epoch: int
    agent_name: str | None
    started_at: float | None
    """Unix timestamp of the sample's start — drives the picker's
    ``running`` column."""

    target: TargetAddress
    """The discovered address for the eval that owns this session."""

    total_tokens: int = 0
    """Running total tokens for the sample — drives the picker's
    ``tokens`` column. Refreshed on the picker's 10s rescan."""


async def enumerate_sessions(
    addresses: list[tuple[str, TargetAddress]],
    *,
    eval_id_filter: str | None = None,
) -> list[SessionRow]:
    """Query each address concurrently for its picker targets.

    ``addresses`` is a list of ``(eval_id, target)`` pairs — typically
    one per discovered eval. For ``--server``, pass a single pair with
    a synthetic eval id (e.g. the address itself) when discovery
    didn't supply one.

    Per-address failures are logged to stderr and dropped — the picker
    still shows surviving rows so a single misbehaving eval doesn't
    blank the whole list. Pass ``eval_id_filter`` to narrow rows after
    aggregation (``--eval-id`` on the CLI).
    """
    if not addresses:
        return []

    async def _query(eval_id: str, target: TargetAddress) -> list[SessionRow] | None:
        try:
            return await _list_for_target(eval_id, target)
        except Exception as exc:
            print(
                f"inspect acp: failed to enumerate {target.describe()}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return None

    results = await asyncio.gather(
        *(_query(eid, addr) for eid, addr in addresses),
        return_exceptions=False,
    )

    rows: list[SessionRow] = []
    for r in results:
        if r is not None:
            rows.extend(r)

    if eval_id_filter is not None:
        rows = [r for r in rows if r.eval_id == eval_id_filter]

    return rows


async def _list_for_target(eval_id: str, target: TargetAddress) -> list[SessionRow]:
    """One enumeration round-trip: initialize → list → close."""
    reader, writer = await _open_socket(target)
    conn = Connection(
        handler=MessageRouter(),
        writer=writer,
        reader=reader,
        listening=True,
    )
    try:
        await conn.send_request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": CLIENT_INFO,
            },
        )
        response: Any = await conn.send_request(INSPECT_LIST_SESSIONS_METHOD, {})
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    sessions = response.get("sessions", []) if isinstance(response, dict) else []
    rows: list[SessionRow] = []
    for s in sessions:
        rows.append(
            SessionRow(
                eval_id=eval_id,
                session_id=s["sessionId"],
                task=s["task"],
                sample_id=s["sampleId"],
                epoch=int(s["epoch"]),
                agent_name=s.get("agentName"),
                started_at=s.get("startedAt"),
                target=target,
                total_tokens=int(s.get("totalTokens") or 0),
            )
        )
    return rows


class AttachedSession:
    """Live ACP connection bound to a single target session.

    Owns the asyncio task running the connection's receive loop. The
    ``disconnected`` event fires when the peer closes (EOF on the
    reader), the receive loop raises, or :meth:`close` is called
    explicitly — so subscribers can ``await disconnected.wait()``
    instead of polling the writer for a closed state.
    """

    def __init__(
        self,
        *,
        connection: Connection,
        writer: asyncio.StreamWriter,
        session_id: str,
        row: SessionRow,
    ) -> None:
        self.connection = connection
        self.writer = writer
        self.session_id = session_id
        self.row = row
        self.disconnected = asyncio.Event()
        self._receive_task: asyncio.Task[None] | None = None
        # Idempotence flag for :meth:`close`. Distinct from
        # ``disconnected`` because the receive loop sets disconnected
        # on peer EOF — at which point we still need to tear down the
        # writer + Connection internals on the local side, so close()
        # must NOT short-circuit on ``disconnected``.
        self._closed = False

    @property
    def is_connected(self) -> bool:
        return not self.disconnected.is_set()

    async def close(self) -> None:
        """Idempotent cleanup; safe to call multiple times.

        Stops the receive task, tears down the ACP Connection (shuts
        down its Dispatcher / Sender background tasks), and closes
        the writer. Called on screen unmount AND after a peer-side
        disconnect — both paths run the same teardown so the asyncio
        loop doesn't end up with orphaned acp.* tasks.

        Teardown order matters: cancel the receive task first so it
        doesn't try to publish a late message into the dispatcher
        queue while ``Connection.close()`` is closing that queue
        (which raises ``RuntimeError: message queue already closed``).
        """
        if self._closed:
            return
        self._closed = True
        # Flag disconnected first so any blocked subscriber wakes up.
        # Harmless no-op when the receive loop already set it.
        self.disconnected.set()
        # Stop the receive task before tearing down the Connection's
        # queue — see method docstring. Task may already be done
        # (peer EOF set disconnected via the loop's finally clause).
        if self._receive_task is not None:
            if not self._receive_task.done():
                self._receive_task.cancel()
            try:
                await self._receive_task
            except (asyncio.CancelledError, Exception):
                pass
        # Connection.close stops the dispatcher + sender loops cleanly;
        # without this the slow TUI suite captures
        # "Task pending: acp.Sender.loop / acp.Dispatcher.loop" warnings
        # whenever the test process exits with a connection still up.
        try:
            await self.connection.close()
        except Exception:
            pass
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


async def attach_session(
    row: SessionRow,
    *,
    on_session_update: Callable[[SessionNotification], None] | None = None,
) -> AttachedSession:
    """Open a fresh connection bound to ``row.session_id``.

    Calls ``initialize`` then ``session/load(sessionId)``. The
    ``session/update`` notification route is registered before the
    receive loop starts; ``on_session_update`` (if given) receives
    each notification synchronously from the receive task.

    The Connection is constructed with ``listening=False`` so we own
    the receive task and can fire :attr:`AttachedSession.disconnected`
    the moment it exits (peer EOF, read error, or explicit close).
    """
    reader, writer = await _open_socket(row.target)
    router = MessageRouter()
    if on_session_update is not None:

        async def _func(params: Any) -> None:
            # MessageRouter delivers params as a dict; validate to the
            # typed SessionNotification so consumers see ACP objects
            # (mirrors the server-side router convention).
            notif = (
                SessionNotification.model_validate(params)
                if isinstance(params, dict)
                else params
            )
            on_session_update(notif)

        router.add_route(
            Route(method="session/update", func=_func, kind="notification")
        )
    conn = Connection(
        handler=router,
        writer=writer,
        reader=reader,
        listening=False,
    )
    session = AttachedSession(
        connection=conn,
        writer=writer,
        session_id=row.session_id,
        row=row,
    )

    async def _run_receive_loop() -> None:
        """Drive the connection's receive loop; flag disconnected on exit."""
        try:
            await conn.main_loop()
        except (asyncio.CancelledError, ConnectionError, OSError):
            # Cancellation = our own close; ConnectionError/OSError =
            # peer EOF or socket error. Both mean "disconnected" —
            # don't propagate.
            pass
        finally:
            session.disconnected.set()

    session._receive_task = asyncio.create_task(
        _run_receive_loop(), name="acp-tui-receive"
    )

    # Handshake — the receive task is already running so responses
    # can be dispatched. If either request raises (e.g. picker row
    # went stale between enumeration and attach, server refuses the
    # session/load), tear down the partially-built session before
    # surfacing the error to the caller — otherwise the socket +
    # background ACP tasks leak.
    try:
        await conn.send_request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": CLIENT_INFO,
            },
        )
        await conn.send_request(
            "session/load",
            {
                "sessionId": row.session_id,
                "cwd": ".",
                "mcpServers": [],
            },
        )
    except BaseException:
        await session.close()
        raise
    return session


async def _open_socket(
    target: TargetAddress,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open an asyncio stream pair for a TargetAddress.

    Mirrors :func:`inspect_ai.agent._acp.stdio._open_socket` — same
    pattern, separate definition because importing the stdio bridge
    just for one helper would be a cross-module dependency for no
    architectural reason.
    """
    if target.socket_path is not None:
        return await asyncio.open_unix_connection(str(target.socket_path))
    if target.host is not None and target.port is not None:
        return await asyncio.open_connection(target.host, target.port)
    raise ValueError(f"invalid TargetAddress: {target.describe()}")
