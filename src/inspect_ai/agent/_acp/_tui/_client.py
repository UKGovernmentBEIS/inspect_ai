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
from typing import Any

from acp import PROTOCOL_VERSION
from acp.connection import Connection
from acp.router import MessageRouter

from inspect_ai.agent._acp._discovery import TargetAddress

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
        response: Any = await conn.send_request("inspect/list_sessions", {})
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

    Owns the asyncio task running the connection's main loop. The
    ``disconnected`` event fires when the peer closes or the loop
    raises; the screen subscribes to drive the disconnect toast.
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

    @property
    def is_connected(self) -> bool:
        return not self.disconnected.is_set()

    async def close(self) -> None:
        """Idempotent cleanup; called on screen unmount + on disconnect."""
        if self.disconnected.is_set():
            return
        self.disconnected.set()
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


async def attach_session(row: SessionRow) -> AttachedSession:
    """Open a fresh connection bound to ``row.session_id``.

    Calls ``initialize`` then ``session/load(sessionId)``. The returned
    handle's connection has ``listening=True`` so notifications would
    flow into the handler — Phase 1 uses an empty router (no
    notification handlers); Phase 2 will register them.
    """
    reader, writer = await _open_socket(row.target)
    conn = Connection(
        handler=MessageRouter(),
        writer=writer,
        reader=reader,
        listening=True,
    )
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
    return AttachedSession(
        connection=conn,
        writer=writer,
        session_id=row.session_id,
        row=row,
    )


async def _open_socket(
    target: TargetAddress,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open an asyncio stream pair for a TargetAddress.

    Mirrors :func:`inspect_ai.agent._acp._stdio._open_socket` — same
    pattern, separate definition because importing the stdio bridge
    just for one helper would be a cross-module dependency for no
    architectural reason.
    """
    if target.socket_path is not None:
        return await asyncio.open_unix_connection(str(target.socket_path))
    if target.host is not None and target.port is not None:
        return await asyncio.open_connection(target.host, target.port)
    raise ValueError(f"invalid TargetAddress: {target.describe()}")
