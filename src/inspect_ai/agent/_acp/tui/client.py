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
import time
from collections.abc import Awaitable, Coroutine
from dataclasses import dataclass, replace
from typing import Any, Callable, Literal

from acp import PROTOCOL_VERSION
from acp.connection import Connection
from acp.exceptions import RequestError
from acp.router import MessageRouter, Route
from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    ElicitationSchema,
    RequestPermissionRequest,
    RequestPermissionResponse,
    SessionNotification,
)

from inspect_ai._util._async import tg_collect
from inspect_ai.agent._acp._config import ACP_STREAM_BUFFER_LIMIT
from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_EVENT_METHOD,
    INSPECT_LIST_SAMPLES_METHOD,
    INTERACTIVE_META_KEY,
    PICKER_META_KEY,
    PLAN_RENDERING_META_KEY,
    RAW_EVENTS_META_KEY,
)
from inspect_ai.agent._acp.tui.state import (
    PendingApproval,
    PendingElicitation,
    SessionState,
)

# JSON-RPC error code for ``invalid_params`` (per JSON-RPC 2.0). The
# server returns this from ``session/load`` when the requested
# sessionId is not in the live target list — the reconnect loop
# treats it as "the sample we were attached to ended during the
# disconnect window" and stops retrying.
_JSONRPC_INVALID_PARAMS = -32602

# Notify severity literal — mirrors Textual's ``app.notify`` severities
# so the screen-side adapter doesn't need to translate.
NotifySeverity = Literal["information", "warning", "error"]

# Reconnect backoff schedule (seconds). After the last entry the loop
# stays at the cap (30s) forever. Forever-retry: the operator hits
# ``^S switch sample`` (already wired) to bail.
_RECONNECT_BACKOFF: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

# Periodic toast cadence while disconnected. First toast fires this
# many seconds after the disconnect started, then again every interval.
# Short reconnects (sub-60s glitches) deliberately don't toast — the
# header dot is the at-a-glance signal; toasts only kick in once the
# operator might have stopped watching.
_DISCONNECT_TOAST_INTERVAL_SECONDS: float = 60.0

CLIENT_INFO = {"name": "inspect-acp-tui", "version": "1"}
"""Sent in ``initialize`` so the server can tailor capability negotiation
(plan rendering, raw events). The TUI is Inspect-aware."""

CLIENT_CAPABILITIES = {
    # Opt in to ``elicitation/create`` (ACP 0.10+, form-mode only).
    # Empty object on ``form`` matches the spec's ``ElicitationFormCapabilities``
    # which is a marker — its mere presence advertises support. Without
    # this the server-side Phase 5 capability gate would leave us off
    # the elicitation registry and ``ask_user`` would fall through to
    # the in-proc panel / console handlers.
    "elicitation": {"form": {}},
    "_meta": {
        PLAN_RENDERING_META_KEY: True,
        RAW_EVENTS_META_KEY: [
            "score",
            "sample_limit",
            "error",
            "compaction",
            "info",
            "span_begin",
            "span_end",
        ],
    },
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

The TUI also subscribes to several raw transcript event types via
:data:`RAW_EVENTS_META_KEY`. Inspect-native events (``score``,
``sample_limit``, ``error``, ``compaction``, ``info``) render as
inline event chips in the transcript — the operator's window into
"the agent stopped because X" without having to crack the log file.
``span_begin`` / ``span_end`` are filtered client-side to the
scoring boundaries: the outer ``span(name="scorers")`` clears the
plan strip when the agent loop exits, and per-scorer
``type="scorer"`` spans mount a ``score · scoring…`` indicator the
moment each scorer begins (giving the operator a positive signal
that scoring has started rather than the session sitting silently in
the gap between react-loop exit and the first score chip);
``span_end`` clears that indicator when the scorer's span closes
without a ``ScoreEvent`` (scorer returned ``None`` or raised — both
legitimate paths that would otherwise leave the indicator pinned
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

    session_id: str | None
    """ACP session uuid; passed to ``session/load`` on attach.

    Set for every attachable sample — including observe-only custom
    solvers. ``None`` only when there's nothing to attach to (no
    transport, the noop placeholder, or a finalized session). Such rows
    appear in the picker dimmed + non-attachable; activation surfaces
    a toast pointing at the intervention docs instead of opening a
    session screen. Whether an attachable row is *drivable* is carried
    separately by :attr:`interactive`."""

    task: str
    sample_id: str
    epoch: int
    agent_name: str | None
    started_at: float | None
    """Unix timestamp of the sample's start — drives the picker's
    ``running`` column."""

    target: TargetAddress
    """The discovered address for the eval that owns this session."""

    total_messages: int = 0
    """Running total messages for the sample — drives the picker's
    ``messages`` column. Refreshed on the picker's 10s rescan."""

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

    interactive: bool = True
    """Whether the session has a bound agent turn loop the operator can
    drive (``session/prompt`` / ``session/cancel``). ``False`` for
    observe-only samples — custom solvers, the pre-bind window, or the
    scoring window. The session screen hides the composer for
    non-interactive sessions (lifecycle controls stay available).
    Default ``True`` for back-compat with servers that omit the flag."""

    pending: Literal["approval", "question"] | None = None
    """Set when the sample is parked on a human-in-the-loop request
    routed through ACP — ``"approval"`` for tool-call permission,
    ``"question"`` for ``ask_user``. ``None`` otherwise. Drives the
    picker's ``pending`` column and primary sort tier."""


async def enumerate_sessions(
    addresses: list[tuple[str, TargetAddress]],
    *,
    eval_id_filter: str | None = None,
    task_filter: str | None = None,
    sample_id_filter: str | None = None,
    epoch_filter: int | None = None,
) -> list[SessionRow]:
    """Query each address concurrently for its picker targets.

    ``addresses`` is a list of ``(eval_id, target)`` pairs — typically
    one per discovered eval. For ``--server``, pass a single pair with
    a synthetic eval id (e.g. the address itself) when discovery
    didn't supply one.

    Per-address failures are logged to stderr and dropped — the picker
    still shows surviving rows so a single misbehaving eval doesn't
    blank the whole list.

    Filters are conjunctive — each non-None one narrows the result.
    ``eval_id_filter`` (``--eval-id`` on the CLI) keeps rows whose
    discovery-side eval id matches exactly; ``task_filter`` /
    ``sample_id_filter`` / ``epoch_filter`` (``--task-id`` / ``--sample-id``
    / ``--epoch``) match the per-session triple components for direct-
    attach via the picker.
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

    results = await tg_collect(
        [
            (lambda eid=eid, addr=addr: _query(eid, addr))  # type: ignore[misc]
            for eid, addr in addresses
        ]
    )

    rows: list[SessionRow] = []
    for r in results:
        if r is not None:
            rows.extend(r)

    if eval_id_filter is not None:
        rows = [r for r in rows if r.eval_id == eval_id_filter]
    if task_filter is not None:
        rows = [r for r in rows if r.task == task_filter]
    if sample_id_filter is not None:
        rows = [r for r in rows if r.sample_id == sample_id_filter]
    if epoch_filter is not None:
        rows = [r for r in rows if r.epoch == epoch_filter]

    return rows


async def _list_for_target(eval_id: str, target: TargetAddress) -> list[SessionRow]:
    """One enumeration round-trip: initialize → list → close.

    Uses ``inspect/list_samples`` (the Inspect-specific superset of
    ``inspect/list_sessions``) so non-ACP samples appear in the
    picker as non-attachable rows alongside the attachable ones.
    """
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
        response: Any = await conn.send_request(INSPECT_LIST_SAMPLES_METHOD, {})
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    samples = response.get("samples", []) if isinstance(response, dict) else []
    rows: list[SessionRow] = []
    for s in samples:
        # ``sessionId`` is ``None`` only for unattachable samples (no
        # transport / noop / finalized). Preserve the None — the picker
        # treats such rows as dimmed + unselectable-on-attach. Attachable
        # rows carry a real id; ``interactive`` says whether they're
        # also drivable.
        pending_raw = s.get("pending")
        pending: Literal["approval", "question"] | None = (
            pending_raw if pending_raw in ("approval", "question") else None
        )
        rows.append(
            SessionRow(
                eval_id=eval_id,
                session_id=s.get("sessionId"),
                task=s["task"],
                sample_id=s["sampleId"],
                epoch=int(s["epoch"]),
                agent_name=s.get("agentName"),
                started_at=s.get("startedAt"),
                target=target,
                total_messages=int(s.get("totalMessages") or 0),
                total_tokens=int(s.get("totalTokens") or 0),
                fails_on_error=bool(s.get("failsOnError", False)),
                interactive=bool(s.get("interactive", True)),
                pending=pending,
            )
        )
    return rows


class AttachedSession:
    """Live ACP connection bound to a single target session.

    Owns the asyncio task running the connection's receive loop AND a
    coordinator task that handles transient transport loss with a
    forever-retrying reconnect loop. The ``disconnected`` event fires
    only on TERMINAL teardown:

    - :meth:`close` is called explicitly (user-initiated ^S switch),
    - the server sent ``inspect/session_ended`` (graceful end),
    - or the reconnect loop got ``invalid_params`` from
      ``session/load`` (the bound sample finished during the
      disconnect window).

    Transient ungraceful disconnects (network glitch, server restart,
    socket drop) are handled internally by the reconnect coordinator:
    it flips :attr:`SessionState.disconnected` True, drives an
    exponential backoff, re-opens the socket, re-runs
    ``initialize`` + ``session/load``, and on success flips
    ``disconnected`` False and resumes. The session swap is invisible
    to the screen — ``self.connection`` / ``self.writer`` are updated
    in place so callers reading ``self._session.connection`` always
    see the live connection.
    """

    def __init__(
        self,
        *,
        connection: Connection,
        writer: asyncio.StreamWriter,
        session_id: str,
        row: SessionRow,
        state: SessionState,
        on_session_update: Callable[[SessionNotification], None] | None = None,
        on_request_permission: Callable[[PendingApproval], None] | None = None,
        on_request_elicitation: Callable[[PendingElicitation], None] | None = None,
        on_inspect_event: Callable[[dict[str, Any]], None] | None = None,
        notify: Callable[[str, NotifySeverity], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.connection = connection
        self.writer = writer
        self.session_id = session_id
        self.row = row
        self.disconnected = asyncio.Event()
        self._receive_task: asyncio.Task[None] | None = None
        self._coordinator_task: asyncio.Task[None] | None = None
        # Idempotence flag for :meth:`close`. Distinct from
        # ``disconnected`` because the receive loop sets disconnected
        # on peer EOF — at which point we still need to tear down the
        # writer + Connection internals on the local side, so close()
        # must NOT short-circuit on ``disconnected``.
        self._closed = False
        # Reconnect machinery — references stored so the coordinator
        # can rebuild the router on each reconnect.
        self._state = state
        self._on_session_update_cb = on_session_update
        self._on_request_permission_cb = on_request_permission
        self._on_request_elicitation_cb = on_request_elicitation
        self._on_inspect_event_cb = on_inspect_event
        self._notify = notify
        self._sleep = sleep
        self._clock = clock
        # Monotonic timestamp of the most recent transition into
        # disconnected state. Read by the toast cadence task to format
        # the "disconnected NNm" message; reset to None on reconnect.
        self._disconnected_at: float | None = None

    @property
    def is_connected(self) -> bool:
        return not self.disconnected.is_set()

    def start_coordinator(self) -> None:
        """Spawn the reconnect coordinator task. Idempotent.

        Called by :func:`attach_session` after the initial handshake
        succeeds. Splits out so tests can construct an AttachedSession
        with a pre-built (mocked) connection and start the coordinator
        explicitly.
        """
        if self._coordinator_task is None or self._coordinator_task.done():
            self._coordinator_task = asyncio.create_task(
                self._coordinator(), name="acp-tui-coordinator"
            )

    async def close(self) -> None:
        """Idempotent cleanup; safe to call multiple times.

        Stops the coordinator + receive task, tears down the ACP
        Connection (shuts down its Dispatcher / Sender background
        tasks), and closes the writer. Called on screen unmount AND
        after a peer-side disconnect — both paths run the same
        teardown so the asyncio loop doesn't end up with orphaned
        acp.* tasks.

        Teardown order matters: cancel the coordinator + receive task
        first so they don't try to publish a late message into the
        dispatcher queue while ``Connection.close()`` is closing that
        queue (which raises ``RuntimeError: message queue already
        closed``).
        """
        if self._closed:
            return
        self._closed = True
        # Flag disconnected first so any blocked subscriber wakes up.
        # Harmless no-op when the receive loop already set it.
        self.disconnected.set()
        # Stop the coordinator first: if a reconnect attempt is in
        # flight it owns a half-built transient connection we don't
        # want to leak. Cancellation propagates into the
        # ``_establish_connection`` call which tears down any partial
        # build in its own finally branches.
        if self._coordinator_task is not None and not self._coordinator_task.done():
            self._coordinator_task.cancel()
            try:
                await self._coordinator_task
            except (asyncio.CancelledError, Exception):
                pass
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

    async def _coordinator(self) -> None:
        """Watch the receive task; reconnect on ungraceful disconnect.

        Runs in a single long-lived task spawned by
        :meth:`start_coordinator`. Outer loop body runs once per
        connection cycle:

        1. Wait for the current receive task to end.
        2. If terminal (closed / session_ended) → return.
        3. Else: flip ``state.disconnected`` True, kick off a toast
           cadence task, drive the reconnect retry loop.
        4. On reconnect success: flip ``state.disconnected`` False,
           emit "Reconnected" toast, loop body restarts against the
           new receive task.
        5. On reconnect getting ``invalid_params`` (target gone):
           mark complete, emit "Sample ended" toast, set
           ``self.disconnected`` (terminal), return.

        The screen-side :meth:`SessionScreen._watch_disconnect` is
        unchanged — it sees ``self.disconnected`` set only on
        terminal teardown, and transient reconnects are invisible to
        it.
        """
        while True:
            if self._receive_task is None:
                # Defensive — should never happen since
                # _establish_connection always assigns one.
                return
            try:
                await self._receive_task
            except (asyncio.CancelledError, Exception):
                pass
            if self._closed:
                self.disconnected.set()
                return
            if self._state.session_ended_received or self._state._complete:
                # Terminal — either server sent ``inspect/session_ended``
                # (graceful end) or the session has otherwise been marked
                # complete. In both cases the sample is over from the
                # operator's POV; reconnecting would just produce
                # noise toasts on a session they're no longer
                # interacting with.
                self.disconnected.set()
                return
            # Ungraceful disconnect. Drive the reconnect cycle.
            self._state.mark_disconnected()
            self._disconnected_at = self._clock()
            toast_task = asyncio.create_task(
                self._toast_cadence(), name="acp-tui-disconnect-toast"
            )
            try:
                session_gone = await self._reconnect_until_resolved()
            except asyncio.CancelledError:
                await _stop_task(toast_task)
                self.disconnected.set()
                raise
            finally:
                await _stop_task(toast_task)
            if session_gone:
                self._state.mark_complete()
                self._disconnected_at = None
                if self._notify is not None:
                    self._notify("Sample ended during disconnect", "warning")
                self.disconnected.set()
                return
            # Reconnect succeeded. Loop body restarts against the
            # freshly-spawned receive task.
            self._state.mark_reconnected()
            self._disconnected_at = None
            if self._notify is not None:
                self._notify("Reconnected to ACP server", "information")

    async def _toast_cadence(self) -> None:
        """Emit a "still trying" toast every interval while disconnected.

        Cancelled by the coordinator on reconnect / session_gone /
        close. The first toast fires at
        ``_DISCONNECT_TOAST_INTERVAL_SECONDS`` (60s) after the
        disconnect — fast glitches don't nag.
        """
        while True:
            await self._sleep(_DISCONNECT_TOAST_INTERVAL_SECONDS)
            if self._notify is None or self._disconnected_at is None:
                continue
            if self._state._complete:
                # Sample is complete — don't nag about a transport
                # the operator is no longer relying on.
                return
            elapsed_s = int(self._clock() - self._disconnected_at)
            mins = max(1, elapsed_s // 60)
            plural = "s" if mins != 1 else ""
            self._notify(
                f"Reconnecting to ACP server (disconnected {mins} minute{plural})",
                "warning",
            )

    async def _reconnect_until_resolved(self) -> bool:
        """Retry ``_establish_connection`` forever (until close / gone).

        Returns True iff ``session/load`` returned ``invalid_params``
        — the bound sample is gone and we should stop. Returns False
        on successful reconnect; the coordinator loops the body.

        Cancellation (close) propagates out as ``CancelledError``;
        the coordinator's outer ``except`` handles it.
        """
        attempt = 0
        while not self._closed and not self._state._complete:
            backoff = _RECONNECT_BACKOFF[min(attempt, len(_RECONNECT_BACKOFF) - 1)]
            await self._sleep(backoff)
            attempt += 1
            if self._closed or self._state._complete:
                return False
            try:
                await self._establish_connection()
                return False
            except RequestError as exc:
                # ``session/load`` rejected our cached target id. The
                # only reason the server returns invalid_params here
                # is "unknown session id" → the sample we were bound
                # to ended during the disconnect window.
                if exc.code == _JSONRPC_INVALID_PARAMS:
                    return True
                # Other JSON-RPC error from initialize / session/load:
                # rare; keep trying (server may transiently mis-route
                # during its own restart).
            except (OSError, ConnectionError):
                # Socket failed to open — server still down. Keep
                # retrying; the operator can ^S out if they want.
                pass
            except Exception:
                # Unexpected — don't crash the coordinator, just
                # back off again. The receive task that the
                # half-built connection might have started is torn
                # down inside _establish_connection's own
                # error-handling.
                pass
        return False

    async def _establish_connection(self) -> None:
        """Open the socket, build a Connection, run the handshake.

        Used by :func:`attach_session` for the initial attach AND by
        the reconnect loop for every subsequent reattach. On reattach,
        tears down any existing connection FIRST (cancel old receive
        task, close old Connection + writer) so the swap is atomic
        from the caller's POV — ``self.connection`` / ``self.writer``
        always reference a live pair (or are about to raise).

        Raises whatever the underlying socket / handshake raised —
        the reconnect loop catches and retries; the initial attach
        propagates to :func:`attach_session`.
        """
        # Tear down any prior connection before opening a new one.
        # First reattach: prior state exists. Initial attach: no-op.
        await _stop_task(self._receive_task)
        self._receive_task = None
        if self.connection is not None:
            try:
                await self.connection.close()
            except Exception:
                pass
        if self.writer is not None:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass

        reader, writer = await _open_socket(self.row.target)
        router = _build_session_router(
            session_ref=self,
            on_session_update=self._on_session_update_cb,
            on_request_permission=self._on_request_permission_cb,
            on_request_elicitation=self._on_request_elicitation_cb,
            on_inspect_event=self._on_inspect_event_cb,
        )
        conn = Connection(
            handler=router,
            writer=writer,
            reader=reader,
            listening=False,
        )
        receive_task = asyncio.create_task(
            _run_receive_loop(conn), name="acp-tui-receive"
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
            await conn.send_request(
                "session/load",
                {
                    "sessionId": self.session_id,
                    "cwd": ".",
                    "mcpServers": [],
                },
            )
            # Clear the per-replay dedup set AFTER ``session/load``
            # returns successfully. The server uses
            # ``_schedule_after_response`` so replay notifications
            # always land after the response; clearing here (not
            # before send_request) means a failed handshake
            # (``invalid_params``, OSError, timeout) leaves
            # ``_replay_reset_message_ids`` untouched — no
            # corruption of dedup state across the retry loop.
            self._state.mark_replay_started()
        except BaseException:
            # Tear down what we just built so the failed attempt
            # doesn't leak. Raise so the caller (initial attach or
            # reconnect loop) can decide what to do.
            await _stop_task(receive_task)
            try:
                await conn.close()
            except Exception:
                pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            raise

        # Commit the swap. Order matters: assign writer before
        # connection so any concurrent reader sees consistent state
        # (writer.close() works regardless of connection state, but
        # connection.send_*() expects the writer to be live).
        self.writer = writer
        self.connection = conn
        self._receive_task = receive_task


async def _run_receive_loop(conn: Connection) -> None:
    """Drive a connection's receive loop until it exits.

    On ANY exit (clean peer EOF, ConnectionError, OSError, our own
    cancellation), close the Connection in a ``finally`` so its
    outgoing-request futures are rejected with
    ``ConnectionError("Connection closed")``. Without this the
    handshake ``await conn.send_request(...)`` in
    :meth:`AttachedSession._establish_connection` would hang forever
    on the pathological case where the server accepts the socket and
    then closes it before answering ``initialize`` or
    ``session/load`` — ``acp.Connection._receive_loop`` treats clean
    EOF as a normal return and does NOT itself reject pending
    futures. Closing here makes the failed handshake observable to
    the reconnect loop so it can back off and retry.

    ``Connection.close()`` is idempotent via its ``_closed`` flag, so
    a subsequent close from :meth:`AttachedSession.close` or
    :meth:`_establish_connection`'s error-path teardown is a no-op.
    """
    try:
        await conn.main_loop()
    except (asyncio.CancelledError, ConnectionError, OSError):
        # Cancellation = our own close; ConnectionError/OSError =
        # peer EOF or socket error. Both are normal exits.
        pass
    finally:
        try:
            await conn.close()
        except Exception:
            pass


async def _stop_task(task: asyncio.Task[Any] | None) -> None:
    """Cancel and await a task; swallow CancelledError + Exception.

    Used at AttachedSession teardown sites (receive task, toast task)
    where we just want to ensure the task has drained before moving
    on — failures and our own cancellation are both expected.
    No-op on ``None`` / already-done.
    """
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def attach_session(
    row: SessionRow,
    *,
    state: SessionState,
    on_session_update: Callable[[SessionNotification], None] | None = None,
    on_request_permission: Callable[[PendingApproval], None] | None = None,
    on_request_elicitation: Callable[[PendingElicitation], None] | None = None,
    on_inspect_event: Callable[[dict[str, Any]], None] | None = None,
    notify: Callable[[str, NotifySeverity], None] | None = None,
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

    ``state`` is the live :class:`SessionState`; the reconnect
    coordinator calls ``state.mark_disconnected`` / ``mark_reconnected``
    / ``mark_session_ended_received`` / ``mark_complete`` on lifecycle
    transitions. ``notify`` (typically wired to Textual's
    ``app.notify``) emits the "disconnected for Nm" / "Reconnected" /
    "Sample ended during disconnect" toasts; pass ``None`` to silence.

    The Connection is constructed with ``listening=False`` so we own
    the receive task and can fire :attr:`AttachedSession.disconnected`
    the moment it terminally exits (peer EOF after the reconnect loop
    gave up, explicit close, or server-confirmed end). Transient
    disconnects are handled internally by the coordinator and never
    fire :attr:`disconnected`.

    Precondition: ``row.session_id is not None``. Non-ACP rows (where
    the sample's agent hasn't claimed ACP) are filtered out by the
    picker's activation guard before this is reached — those rows
    surface a toast pointing at the intervention docs instead.
    """
    if row.session_id is None:
        raise ValueError(
            "attach_session called with a non-ACP row "
            "(row.session_id is None); pick a row whose agent has "
            "claimed ACP, or surface the intervention-docs toast."
        )
    session = AttachedSession(
        # ``connection`` / ``writer`` are placeholders here — the
        # real values are assigned by ``_establish_connection`` below.
        # mypy: passing ``None`` would require Optional in the dataclass;
        # instead we cast and let the assignment populate immediately.
        connection=None,  # type: ignore[arg-type]
        writer=None,  # type: ignore[arg-type]
        session_id=row.session_id,
        row=row,
        state=state,
        on_session_update=on_session_update,
        on_request_permission=on_request_permission,
        on_request_elicitation=on_request_elicitation,
        on_inspect_event=on_inspect_event,
        notify=notify,
    )
    try:
        await session._establish_connection()
    except BaseException:
        await session.close()
        raise
    session.start_coordinator()
    return session


def _build_session_router(
    *,
    session_ref: "AttachedSession",
    on_session_update: Callable[[SessionNotification], None] | None,
    on_request_permission: Callable[[PendingApproval], None] | None,
    on_request_elicitation: Callable[[PendingElicitation], None] | None,
    on_inspect_event: Callable[[dict[str, Any]], None] | None,
) -> MessageRouter:
    """Build the route table for ONE connection cycle.

    Called on initial attach AND each reconnect — every connection
    needs its own fresh router (acp.Connection owns its router for
    the connection's lifetime; reusing across reconnects would attach
    the old router's task supervisor to the new connection).

    ``session_ref`` is the long-lived :class:`AttachedSession`; the
    handlers close over it to update ``session_ref.row`` from binding
    meta and to call ``session_ref._state.mark_session_ended_received``
    on the ``inspect/session_ended`` notification.
    """
    router = MessageRouter()
    if on_request_permission is not None:
        _register_permission_route(router, on_request_permission)

    if on_request_elicitation is not None:
        _register_elicitation_route(router, on_request_elicitation)

    if on_session_update is not None:

        async def _on_session_update(params: Any) -> None:
            # MessageRouter delivers params as a dict; validate to the
            # typed SessionNotification so consumers see ACP objects
            # (mirrors the server-side router convention).
            notif = (
                SessionNotification.model_validate(params)
                if isinstance(params, dict)
                else params
            )
            # Direct-attach AND reconnect (also via ``session/load``)
            # both land here. The server's binding-confirmation
            # notification carries the authoritative target metadata
            # under PICKER_META_KEY; peek for it and refresh
            # ``session_ref.row`` before the modal could ever read a
            # stale value. SessionState.consume drops the picker meta
            # entirely (treating it as cosmetic bind chrome), so this
            # is the only place the wire data lands on the client.
            _refresh_row_from_binding_meta(session_ref, notif)
            on_session_update(notif)

        router.add_route(
            Route(method="session/update", func=_on_session_update, kind="notification")
        )

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

    async def _on_session_ended(params: Any) -> None:
        await _handle_session_ended(session_ref, params)

    router.add_route(
        Route(
            method="inspect/session_ended",
            func=_on_session_ended,
            kind="notification",
        )
    )
    return router


async def _handle_session_ended(session_ref: "AttachedSession", params: Any) -> None:
    """Translate the server's clean-end notification into local state.

    Three things happen in strict order:

    1. ``mark_session_ended_received()`` — the coordinator's
       graceful-vs-ungraceful gate reads this flag when the
       receive loop subsequently exits, so the flag must be set
       BEFORE anything else that could cause the loop to exit.
    2. ``mark_complete()`` — flips the lifecycle pill to
       ``complete``; idempotent.
    3. ``session_ref.disconnected.set()`` — wakes the screen's
       ``_watch_disconnect`` to run ``session.close()`` and tear
       down the ACP Connection + receive task + writer + socket.
       Critical: the server keeps the transport OPEN after
       sending ``inspect/session_ended`` (the connection is
       reusable for picker → another sample), so without this
       the receive loop never exits, the writer + Dispatcher +
       Sender background tasks leak, and the socket fd stays
       open on a completed sample until the user switches
       samples or the eval ends.

    Identity guard against stray notifications for a different
    sessionId (shouldn't happen on a one-connection-per-session
    client, but cheap to enforce).

    Extracted to module scope so tests can drive the handler
    directly without indexing ``MessageRouter._notifications``
    (a private dict whose layout the ``acp`` library is free to
    change).
    """
    ended_id = params.get("sessionId") if isinstance(params, dict) else None
    if ended_id != session_ref.session_id:
        return
    session_ref._state.mark_session_ended_received()
    session_ref._state.mark_complete()
    session_ref.disconnected.set()


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
    operator UI on the direct-attach path that never enumerated through
    the picker:

    - ``failsOnError`` (per-entry under :data:`PICKER_META_KEY`) — the
      cancel-sample modal gates its ``[e] error`` action on it.
    - ``inspect.interactive`` (on the OUTER ``_meta``, not the entry) —
      the session screen hides the composer for observe-only sessions.

    No-op when the notification carries neither signal or when the
    values already match what the row holds — keeps subscriber spam
    quiet.
    """
    meta = getattr(notification, "field_meta", None) or {}

    # Interactivity rides on the outer _meta of the binding confirmation
    # (the picker notification doesn't carry it, so it's absent there).
    interactive_raw = meta.get(INTERACTIVE_META_KEY)
    if isinstance(interactive_raw, bool) and interactive_raw != session.row.interactive:
        session.row = replace(session.row, interactive=interactive_raw)

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


def _make_elicitation_handler(
    on_request_elicitation: Callable[[PendingElicitation], None],
) -> Callable[[Any], Coroutine[Any, Any, dict[str, Any]]]:
    """Build the ``elicitation/create`` handler closure.

    Mirrors :func:`_make_permission_handler` one-for-one:

    - Validates ``params`` to the standard ACP wire shape for a
      session-scoped form elicitation —
      ``{message, mode: "form", sessionId, toolCallId?, requestedSchema}``.
      The installed ``acp.schema`` 0.10 splits this across two Pydantic
      classes (``CreateFormElicitationRequest`` + ``ElicitationFormSessionMode``)
      and offers no merged validator; we read the fields directly and
      let :class:`ElicitationSchema.model_validate` police the schema
      shape.
    - Creates a :class:`PendingElicitation` (with a fresh
      ``asyncio.Event``) and hands it to the screen-side callback,
      which parks it on :attr:`SessionState.pending_elicitation` via
      :meth:`SessionState.consume_elicitation_request`.
    - Parks on ``pending.event``. The card's submit / decline button
      (or one of the session cancel paths via
      :meth:`SessionState.resolve_elicitation`) fires the event and
      populates the resolution fields.
    - Returns the JSON-RPC response dict mapping back to ACP's
      discriminated union: ``{action: "accept", content: {...}}`` /
      ``{action: "decline"}`` / ``{action: "cancel"}``.

    Cancellation: ``asyncio.CancelledError`` (screen unmount /
    disconnect) sets the pending as cancelled and fires the event so
    any other reader sees a consistent state, then re-raises.
    """

    async def _handler(params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ValueError(
                f"elicitation/create params must be a dict, got {type(params).__name__}"
            )
        mode = params.get("mode")
        if mode != "form":
            # Phase 6a supports form-mode only; URL-mode is deferred per
            # the elicitation design doc's "Out of scope" section.
            raise ValueError(
                f"elicitation/create mode={mode!r} is not supported; "
                "Inspect TUI only handles form-mode elicitation"
            )
        message = params.get("message")
        if not isinstance(message, str):
            raise ValueError("elicitation/create missing required 'message' field")
        raw_schema = params.get("requestedSchema")
        if raw_schema is None:
            raise ValueError(
                "elicitation/create form-mode missing required 'requestedSchema' field"
            )
        schema = ElicitationSchema.model_validate(raw_schema)
        tool_call_id_raw = params.get("toolCallId")
        tool_call_id = tool_call_id_raw if isinstance(tool_call_id_raw, str) else None
        pending = PendingElicitation(
            message=message,
            requested_schema=schema,
            event=asyncio.Event(),
            tool_call_id=tool_call_id,
        )
        try:
            on_request_elicitation(pending)
            await pending.event.wait()
        except (asyncio.CancelledError, Exception):
            if not pending.event.is_set():
                pending.action = "cancel"
                pending.event.set()
            raise
        # action is set by resolve_elicitation; defensive default is
        # cancel so a half-resolved state never leaks an accept with no
        # content out onto the wire.
        action = pending.action or "cancel"
        if action == "accept":
            return {"action": "accept", "content": pending.content or {}}
        return {"action": action}

    return _handler


def _register_elicitation_route(
    router: MessageRouter,
    on_request_elicitation: Callable[[PendingElicitation], None],
) -> None:
    """Register the elicitation/create handler on the client router."""
    router.add_route(
        Route(
            method="elicitation/create",
            func=_make_elicitation_handler(on_request_elicitation),
            kind="request",
        )
    )
