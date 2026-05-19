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
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from typing import Any, Callable

from acp import PROTOCOL_VERSION
from acp.connection import Connection
from acp.router import MessageRouter, Route
from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    RequestPermissionRequest,
    RequestPermissionResponse,
    SessionNotification,
)

from inspect_ai.agent._acp._config import ACP_STREAM_BUFFER_LIMIT
from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_EVENT_METHOD,
    INSPECT_LIST_SESSIONS_METHOD,
    PICKER_META_KEY,
    PLAN_RENDERING_META_KEY,
    RAW_EVENTS_META_KEY,
)
from inspect_ai.agent._acp.tui.state import PendingApproval

CLIENT_INFO = {"name": "inspect-acp-tui", "version": "1"}
"""Sent in ``initialize`` so the server can tailor capability negotiation
(plan rendering, raw events). The TUI is Inspect-aware."""

CLIENT_CAPABILITIES = {
    "_meta": {
        PLAN_RENDERING_META_KEY: True,
        RAW_EVENTS_META_KEY: ["score", "span_begin", "span_end"],
    }
}
"""ACP ``clientCapabilities`` advertised in ``initialize``.

The TUI opts in to plan rendering: the server's
:class:`PlanPolicyTransformer` substitutes ``AgentPlanUpdate`` for the
standard tool-call notifications of ``update_plan`` / ``todo_write``,
which the plan strip widget consumes as its single source of truth.
The TUI is not in the server's ``PLAN_RENDERING_CLIENTS`` allowlist
(which exists for third-party editors we can't ask to opt in
explicitly — Zed, Toad); ``_meta`` is the right path for first-party
clients we control.

The TUI also subscribes to ``score``, ``span_begin``, and ``span_end``
via :data:`RAW_EVENTS_META_KEY`. Score events drive the mid-stream
score chip. ``span_begin`` is filtered client-side to the per-scorer
``type="scorer"`` spans so the TUI can mount a ``score · scoring…``
indicator the moment each scorer begins, giving the operator a
positive signal that scoring has started rather than the session
sitting silently in the gap between react-loop exit and the first
score chip. ``span_end`` clears that indicator when the scorer's span
closes without a ``ScoreEvent`` (scorer returned ``None`` or raised —
both legitimate paths that would otherwise leave the indicator pinned
forever).

``_meta`` is the JSON wire key; ACP's Pydantic schema serializes it
from ``ClientCapabilities.field_meta``. We construct the wire shape
directly here since the request is sent as a raw JSON-RPC payload."""


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

    fails_on_error: bool = False
    """Whether the sample is configured to fail immediately on errors
    (server-side ``ActiveSample.fails_on_error``). Drives the
    cancel-sample modal's polarity: when ``True``, the operator's
    ``action="error"`` disposition is hidden (the sample would error
    on its own; only ``action="score"`` is meaningful). Default
    ``False`` for back-compat with older servers that don't carry the
    field on the ``inspect/list_sessions`` response or binding-
    confirmation ``_meta``."""


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
                "clientCapabilities": CLIENT_CAPABILITIES,
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
                fails_on_error=bool(s.get("failsOnError", False)),
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
    on_request_permission: Callable[[PendingApproval], None] | None = None,
    on_inspect_event: Callable[[dict[str, Any]], None] | None = None,
) -> AttachedSession:
    """Open a fresh connection bound to ``row.session_id``.

    Calls ``initialize`` then ``session/load(sessionId)``. Route
    registrations happen before the receive loop starts:

    - ``session/update`` (notification): ``on_session_update`` (if
      given) receives each notification synchronously.
    - ``session/request_permission`` (request): ``on_request_permission``
      (if given) receives a fresh :class:`PendingApproval` and must
      arrange for somebody to call
      :meth:`SessionState.resolve_approval` on the matching tool_call_id
      so this handler can fire its response back over the wire.
    - ``inspect/event`` (notification, opt-in): ``on_inspect_event``
      (if given) receives the raw transcript event payload — the TUI
      subscribes to ``["score"]`` so mid-stream scoring chips can
      render. The payload is a serialized ``inspect_ai.event.Event``;
      consumers route by the ``event`` discriminator.

    The Connection is constructed with ``listening=False`` so we own
    the receive task and can fire :attr:`AttachedSession.disconnected`
    the moment it exits (peer EOF, read error, or explicit close).
    """
    reader, writer = await _open_socket(row.target)
    router = MessageRouter()
    if on_request_permission is not None:
        _register_permission_route(router, on_request_permission)
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

    # Define the session/update route AFTER ``session`` is constructed
    # so the handler closure can refresh ``session.row`` from the
    # binding-confirmation notification's picker meta — see the
    # _refresh_row_from_binding_meta call below.
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
            # Direct-attach path (``session/load`` without going through
            # the picker) starts with whatever defaults the SessionRow
            # had at construction time — fails_on_error defaults to
            # False. The server's binding-confirmation notification
            # carries the authoritative target metadata under the same
            # PICKER_META_KEY the picker uses, so peek for it here and
            # refresh the row before the modal could ever read a stale
            # value. SessionState.consume drops the picker meta entirely
            # (treating it as cosmetic bind chrome), so this is the only
            # place the wire data lands on the client.
            _refresh_row_from_binding_meta(session, notif)
            on_session_update(notif)

        router.add_route(
            Route(method="session/update", func=_func, kind="notification")
        )

    # Server-side ``inspect/event`` raw firehose. The TUI subscribes to
    # ``["score"]`` so a scorer firing during the post-agent scoring
    # phase surfaces as a chip in the transcript. Routed by the
    # client-supplied callback; the route is always registered so a
    # late-added subscription has no listener-shape mismatch.
    if on_inspect_event is not None:

        async def _on_inspect_event(params: Any) -> None:
            if isinstance(params, dict):
                on_inspect_event(params)

        router.add_route(
            Route(
                method=INSPECT_EVENT_METHOD,
                func=_on_inspect_event,
                kind="notification",
            )
        )

    # Server-side ``inspect/session_ended`` notification → flip the
    # session's ``disconnected`` event. The SessionScreen's watcher
    # treats that as "this session is done" and flips the lifecycle
    # pill to ``complete``. This is what gives us a positive
    # end-of-session signal mid-eval; without it, a client bound to
    # an early-finishing sample wouldn't see ``complete`` until the
    # entire eval shut down and the transport closed.
    async def _on_session_ended(params: Any) -> None:
        ended_id = params.get("sessionId") if isinstance(params, dict) else None
        # Identity guard so a stray notification meant for a different
        # bound session (shouldn't happen on a one-connection-per-
        # session client, but cheap to enforce) doesn't tear ours
        # down prematurely.
        if ended_id == session.session_id:
            session.disconnected.set()

    router.add_route(
        Route(
            method="inspect/session_ended",
            func=_on_session_ended,
            kind="notification",
        )
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
                "clientCapabilities": CLIENT_CAPABILITIES,
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
    architectural reason. Uses the same :data:`ACP_STREAM_BUFFER_LIMIT`
    so the receive loop survives a multi-hundred-KB ``ScoreEvent`` on
    swe-bench-style scorers.
    """
    if target.socket_path is not None:
        return await asyncio.open_unix_connection(
            str(target.socket_path), limit=ACP_STREAM_BUFFER_LIMIT
        )
    if target.host is not None and target.port is not None:
        return await asyncio.open_connection(
            target.host, target.port, limit=ACP_STREAM_BUFFER_LIMIT
        )
    raise ValueError(f"invalid TargetAddress: {target.describe()}")


def _make_permission_handler(
    on_request_permission: Callable[[PendingApproval], None],
) -> Callable[[Any], Coroutine[Any, Any, dict[str, Any]]]:
    """Build the ``session/request_permission`` handler closure.

    Extracted from :func:`_register_permission_route` so tests can
    exercise the handler directly without a live socket round-trip.

    Handler contract:
    - Validates ``params`` to :class:`RequestPermissionRequest`.
    - Creates a :class:`PendingApproval` (with a fresh
      ``asyncio.Event``) and hands it to the screen-side callback,
      which attaches it to the matching tool-call card via
      :meth:`SessionState.consume_approval_request`.
    - Parks on ``pending.event``. The button-press handler in
      :class:`SessionScreen` calls :meth:`SessionState.resolve_approval`
      which fires the event and populates the resolution flags.
    - Returns a JSON-RPC-serializable response dict:
      - ``chosen_option_id`` set → ``AllowedOutcome(outcome="selected", optionId=...)``.
      - Otherwise (cancelled / decided_elsewhere) →
        ``DeniedOutcome(outcome="cancelled")``.

    Cancellation: ``asyncio.CancelledError`` (screen unmount /
    disconnect) sets ``pending.cancelled`` and fires the event so
    any other reader sees a consistent state, then re-raises so the
    JSON-RPC dispatcher abandons the response.
    """

    async def _handler(params: Any) -> dict[str, Any]:
        request = RequestPermissionRequest.model_validate(params)
        pending = PendingApproval(request=request, event=asyncio.Event())
        # Invoke the screen-side callback INSIDE the try block so a
        # synchronous exception from it (e.g. a Textual ``NoMatches``
        # if the screen has just unmounted, or any other unexpected
        # error) still marks the pending as cancelled and fires the
        # event before propagating. Otherwise any concurrent reader
        # holding the ``PendingApproval`` reference would observe a
        # half-initialised slot, and the server's request future
        # would be permanently parked waiting for a response we'll
        # never send.
        try:
            on_request_permission(pending)
            await pending.event.wait()
        except (asyncio.CancelledError, Exception):
            if not pending.event.is_set():
                pending.cancelled = True
                pending.event.set()
            raise
        if pending.chosen_option_id is not None:
            response = RequestPermissionResponse(
                outcome=AllowedOutcome(
                    outcome="selected", option_id=pending.chosen_option_id
                )
            )
        else:
            response = RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled")
            )
        return response.model_dump(mode="json", by_alias=True, exclude_none=True)

    return _handler


def _refresh_row_from_binding_meta(
    session: AttachedSession, notification: SessionNotification
) -> None:
    """Update ``session.row`` from binding-confirmation picker meta.

    The server sends a ``session/update`` on bind whose ``_meta``
    carries the authoritative target dict (``picker_target_meta_dict``)
    under :data:`PICKER_META_KEY`. The TUI's :class:`SessionState`
    drops the whole notification as cosmetic bind chrome, so this
    runs BEFORE that drop and pulls out the fields that drive
    operator UI (currently just ``failsOnError`` — the cancel-sample
    modal needs it to gate the ``[e] error`` action even on the
    direct-attach path that never enumerated through the picker).

    No-op when the notification carries no picker meta, when no entry
    matches our session id, or when the entry's ``failsOnError`` is
    already what the row holds — keeps subscriber spam quiet.
    """
    meta = getattr(notification, "field_meta", None) or {}
    entries = meta.get(PICKER_META_KEY)
    if not isinstance(entries, list):
        return
    # The binding-confirmation carries exactly one entry (the bound
    # target); the picker notification carries many. Match by
    # session_id so we update on the right entry in either shape.
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("sessionId") != session.session_id:
            continue
        fails_on_error = bool(entry.get("failsOnError", session.row.fails_on_error))
        if fails_on_error != session.row.fails_on_error:
            # SessionRow is a frozen dataclass; replace produces a
            # fresh instance with the updated field.
            session.row = replace(session.row, fails_on_error=fails_on_error)
        return


def _register_permission_route(
    router: MessageRouter,
    on_request_permission: Callable[[PendingApproval], None],
) -> None:
    """Register the permission-request handler on the client router."""
    router.add_route(
        Route(
            method="session/request_permission",
            func=_make_permission_handler(on_request_permission),
            kind="request",
        )
    )
