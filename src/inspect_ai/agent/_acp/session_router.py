"""Per-bind outbound forwarder: transcript events → ACP session/update.

The :class:`Forwarders` class owns the lifecycle of a single bind:
attach to a target :class:`AcpTransport`'s pub/sub bus + transcript
subscriber list, run the live forwarder task(s), and tear everything
down on rebind / disconnect. Each bind creates a fresh
:class:`Forwarders` instance — its per-bind state (plan-tool stash,
in-flight tasks, subscriber handles) cannot leak across binds because
the object itself is destroyed.

asyncio anchor — this module is **asyncio-bound** at the ``acp.Connection``
boundary. See ``design/acp/agent-acp.md`` "asyncio / anyio boundary"
for the rationale.
"""

from __future__ import annotations

import asyncio
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Iterator

import anyio
from acp.connection import Connection
from acp.meta import CLIENT_METHODS
from acp.schema import SessionNotification

from inspect_ai.agent._acp._guards import SendStatus, acp_guard, acp_send_guard
from inspect_ai.agent._acp.event_mapping import (
    ReplayTranscriptor,
    SubagentDepthTracker,
)
from inspect_ai.agent._acp.inspect_ext import (
    INSPECT_SESSION_ENDED_METHOD,
    REPLAY_META_KEY,
    PlanPolicyTransformer,
    RawEventForwarder,
)

if TYPE_CHECKING:
    from inspect_ai.agent._acp.connection import ConnectionState
    from inspect_ai.agent._acp.transport import (
        AcpTransport,
        ApproverClient,
        ElicitationClient,
    )

logger = getLogger(__name__)

# Standard ACP method used by the semantic forwarder.
_SESSION_UPDATE_METHOD = CLIENT_METHODS["session_update"]

# ``REPLAY_MAX_EVENTS`` caps replay payload size on late attach so a
# very long-running sample doesn't dump thousands of events on every
# new connection. Applied per-stream to the respective universe (last N
# filtered semantic events, last N raw events) — see
# ``_run_replay``. The snapshot itself reads the full since-attach
# history from the buffer history provider (which resolves attachment
# content), so this cap is purely a wire-payload bound, independent of
# the transcript's resident window.
REPLAY_MAX_EVENTS = 100

# How long :meth:`Forwarders.stop` waits for the semantic task to
# finish its EOF cleanup naturally before falling through to cancel.
# On the standard end-of-sample path :meth:`LiveAcpTransport.finalize`
# has already closed pubsub by the time ``stop()`` is called, so the
# task is racing to drain the raw forwarder and send
# ``inspect/session_ended`` — both finish within microseconds. The
# cap protects the disconnect path where the task may be parked on
# a receive that won't deliver (sample cut short) or a send that
# won't return (peer gone but the socket hasn't surfaced the EOF
# yet). 1.5s is plenty of headroom for the cleanup branch without
# noticeably slowing eval shutdown if the task is genuinely stuck.
_GRACEFUL_STOP_TIMEOUT_SECONDS = 1.5


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _stamp_replay_marker(notification: SessionNotification) -> SessionNotification:
    """Return a copy of ``notification`` with the replay marker stamped.

    Sets :data:`REPLAY_META_KEY` = ``True`` on the OUTER
    ``SessionNotification.field_meta`` (preserving any existing keys
    via merge — picker bind-confirmation notifications carry the
    picker meta on the same surface). Used by :meth:`Forwarders._run_replay`
    so the client can dedup against chunks it already rendered for the
    same message_id (typical on reconnect: server replays the snapshot
    tail; client has prior state). Live forwarding never stamps this
    marker.

    Immutable update: ``SessionNotification`` is a Pydantic model;
    callers must not mutate notifications in place because the
    underlying transcript event objects can be shared with other
    consumers (the log writer, in-process TUI, etc.).
    """
    existing = getattr(notification, "field_meta", None) or {}
    merged = {**existing, REPLAY_META_KEY: True}
    return notification.model_copy(update={"field_meta": merged})


def _filter_subagent_events(events: list[Any]) -> Iterator[Any]:
    """Yield only top-level events (depth==0 by sub-agent spans).

    Mirrors the depth-tracking the live router and replay helper use,
    but returns events (not session notifications) so callers can apply
    counting / slicing / further transforms before mapping. Span
    begin/end markers are consumed (never yielded — they're
    bookkeeping, not user-visible content).
    """
    tracker = SubagentDepthTracker()
    for event in events:
        if tracker.process(event) == "emit":
            yield event


# ---------------------------------------------------------------------------
# Forwarders
# ---------------------------------------------------------------------------


class Forwarders:
    """Per-bind outbound forwarder + replay + plan-policy state.

    Owns:
    - Subscriber stream to the target's pub/sub bus (the
      ``session/update`` source).
    - Transcript subscriber (the ``inspect/event`` raw source, opt-in).
    - Approver client registration so the configured
      ``human_approver`` can route through this connection.
    - Plan-tool stash (per-tool buffer for the in-progress → completed
      transition of ``update_plan`` / ``todo_write``).
    - The two background asyncio tasks that drain the streams.

    Lifecycle: ``start()`` per bind; ``stop()`` on rebind / disconnect.
    Construct one instance per bind so per-bind state (notably the
    plan-tool stash) is fresh — never leaks across rebinds.
    """

    def __init__(
        self,
        state: "ConnectionState",
        connection: Connection,
        approver_client: "ApproverClient",
        elicitation_client: "ElicitationClient | None" = None,
        *,
        target_session_id: str,
        wire_session_id: str,
    ) -> None:
        self._state = state
        self._connection = connection
        self._approver_client = approver_client
        # Elicitation client is None when the peer didn't advertise
        # ``elicitation.form`` capability in ``initialize`` — gated by
        # ``ConnectionState.client_supports_elicitation_form``.
        self._elicitation_client = elicitation_client
        # IDs captured at construction. Per-bind; immutable for the
        # lifetime of this Forwarders instance. Reading from
        # ``self._state.wire_session_id`` later would be incorrect on
        # rebind paths where the connection's state has moved on but
        # this Forwarders is still draining buffered events.
        self._target_session_id = target_session_id
        self._wire_session_id = wire_session_id
        # Forwarder runtime — populated by ``start()``.
        self._target: "AcpTransport | None" = None
        self._semantic_stream: Any = None
        self._semantic_task: asyncio.Task[None] | None = None
        # Inspect extensions, fresh per-bind. The raw-event forwarder
        # is created lazily — only when the client opted in via
        # ``inspect.raw_events`` — to avoid allocating its bridge
        # stream for the common non-opted case.
        self._raw_forwarder: RawEventForwarder | None = None
        self._plan_policy = PlanPolicyTransformer(state)
        # Approver client unsubscribe callable.
        self._approver_unsub: Callable[[], None] | None = None
        # Elicitation client unsubscribe callable (only set when the
        # peer advertised ``elicitation.form`` capability).
        self._elicitation_unsub: Callable[[], None] | None = None
        # Drain barrier — see :meth:`drain` and ``_run_semantic_forwarder``.
        # ``_notifications_sent`` counts items the forwarder has
        # fully processed (transform + send + finally tick). The
        # event fires (and gets replaced with a fresh one) on every
        # increment so ``drain`` waiters can re-check the counter
        # on each tick.
        #
        # ``_processing_item`` flips True the moment the forwarder
        # has PULLED an item from the stream but has not yet
        # finished its try/finally for that item. The drain barrier
        # MUST account for this in-flight window: the item is no
        # longer in ``current_buffer_used`` (the stream's
        # statistics) but also hasn't bumped the counter — without
        # tracking it explicitly, ``drain`` would see "buffer empty
        # + counter still N" and return BEFORE that item's send
        # completes, defeating the whole ordering guarantee.
        self._notifications_sent: int = 0
        self._sent_event: anyio.Event = anyio.Event()
        self._processing_item: bool = False

    async def start(self, target: "AcpTransport") -> None:
        """Begin live forwarding for a freshly-bound target session.

        Three-step setup ordered to avoid both lost events AND
        replay/live duplicates:

        1. **Snapshot transcript events** for replay (sync).
        2. **Attach live subscribers** (sync) — new events from this
           point land in the live forwarder's buffer.
        3. Start the **live forwarder task(s)**, but defer their
           ``send_notification`` work until after **replay completes**
           (replay emits ``session/update`` and ``inspect/event``
           notifications in order before any live ones go out).

        Snapshot + attach are both sync (no ``await`` between them),
        so no event can slip into both — events ≤ snapshot index go
        through replay; events > snapshot index go through live.

        Caller (``ConnectionHandler._start_forwarders``) holds
        ``_bind_lock``, so no concurrent bind can interleave with
        this method's awaits. No per-await rebind checks are needed.
        """
        self._target = target

        # SNAPSHOT (sync) — captures everything that's happened so far.
        snapshot = list(target.transcript_events_snapshot())

        # ATTACH live subscribers (also sync) — from here on new events
        # go into the live buffers, not the snapshot.
        self._semantic_stream = target.attach()
        subscription = self._state.raw_events_subscription
        if subscription is not None:
            self._raw_forwarder = RawEventForwarder(
                self._connection, subscription=subscription
            )
            self._raw_forwarder.attach(target)

        # Register as an approver client so the configured
        # ``human_approver`` can route tool-approval prompts here.
        self._approver_unsub = target.attach_approver_client(self._approver_client)
        # Register as an elicitation client only when the peer
        # advertised ``elicitation.form`` capability — clients without
        # that capability would silently drop ``elicitation/create``.
        if self._elicitation_client is not None:
            self._elicitation_unsub = target.attach_elicitation_client(
                self._elicitation_client
            )

        # REPLAY — emit historical notifications synchronously before
        # live ones. Raw replay (if enabled) first, then semantic.
        # If replay exits early because a send failed (peer disconnect
        # or any other transport error), the underlying ``acp`` library's
        # sender task has died — a subsequent live ``send_notification``
        # would enqueue a future with no sender left to complete it.
        # Tear down what we've already attached and bail. We can't rely
        # on ``Connection.main_loop`` exiting to trigger our outer
        # cleanup: ``acp``'s ``TaskSupervisor`` only logs the dead-task
        # failure, it doesn't close the receive loop. Without an
        # explicit ``stop()`` here, the semantic pub/sub subscriber,
        # raw transcript subscriber, and approver registration would
        # all stay attached with no forwarder tasks draining them.
        # ``stop()`` is idempotent and handles partial state (no
        # ``_semantic_task`` yet, possibly-not-started raw forwarder).
        replay_status = await self._run_replay(snapshot)
        if replay_status.should_exit:
            await self.stop()
            return

        # LIVE forwarders — drain the buffers that have been filling
        # since attach.
        self._semantic_task = asyncio.create_task(
            self._run_semantic_forwarder(target, self._semantic_stream),
            name=f"acp-fwd-semantic-{self._target_session_id}",
        )
        if self._raw_forwarder is not None:
            self._raw_forwarder.start(self._target_session_id)

    async def stop(self, *, graceful: bool = False) -> None:
        """Cancel forwarder tasks + detach subscribers. Idempotent.

        ``graceful=True`` (used by :meth:`AcpServer.stop` during the
        end-of-eval teardown) gives the semantic task a brief grace
        window to finish its EOF cleanup naturally before falling
        through to ``cancel``. The cleanup branch drains the raw
        forwarder and sends ``inspect/session_ended``; on the
        standard end-of-sample path ``finalize()`` has already closed
        pubsub by this point, so the task is racing to complete that
        branch and finishes within microseconds. The
        :data:`_GRACEFUL_STOP_TIMEOUT_SECONDS` cap bounds the wait
        for the corner case where the task is parked on a send that
        won't return (peer gone but the socket hasn't surfaced the
        EOF yet). Without this window the client never sees
        ``inspect/session_ended`` on eval completion — the cancel
        beats the send to the wire.

        ``graceful=False`` (default — used by the connection-disconnect
        path) cancels immediately. The peer is gone, so there's no
        point waiting for a send that has nowhere to go; pubsub is
        still open (the session outlives the disconnected
        connection), so the task is parked in its main loop and
        would otherwise hit the full timeout for no benefit.
        """
        # Deregister as an approver / elicitation client so a pending
        # or post-disconnect prompt doesn't try to send through a
        # closed connection.
        if self._approver_unsub is not None:
            try:
                self._approver_unsub()
            except Exception:
                logger.exception("Error detaching ACP approver client")
            self._approver_unsub = None
        if self._elicitation_unsub is not None:
            try:
                self._elicitation_unsub()
            except Exception:
                logger.exception("Error detaching ACP elicitation client")
            self._elicitation_unsub = None
        if self._semantic_task is not None and not self._semantic_task.done():
            if graceful:
                try:
                    # ``asyncio.shield`` so the outer ``wait_for``
                    # timeout doesn't cascade-cancel the task itself
                    # — we want the timeout to fall through to the
                    # explicit ``cancel()`` below, not to leave the
                    # task in a half-cancelled state mid-send.
                    await asyncio.wait_for(
                        asyncio.shield(self._semantic_task),
                        timeout=_GRACEFUL_STOP_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass
                except (anyio.get_cancelled_exc_class(), Exception):
                    # Task exited with an exception during the grace
                    # window — that's fine, we were waiting for it to
                    # finish either way. ``cancel()`` below is a
                    # no-op on a done task.
                    pass
            if not self._semantic_task.done():
                self._semantic_task.cancel()
                try:
                    await self._semantic_task
                except (anyio.get_cancelled_exc_class(), Exception):
                    pass
        self._semantic_task = None
        # Raw forwarder shutdown runs AFTER the semantic grace window:
        # the semantic task's EOF branch awaits ``raw_forwarder.drain()``
        # before sending session_ended, so the raw forwarder must be
        # alive while that's happening. Stopping it first would race
        # the drain barrier.
        if self._raw_forwarder is not None:
            await self._raw_forwarder.stop()
            self._raw_forwarder = None
        if self._target is not None and self._semantic_stream is not None:
            try:
                self._target.detach(self._semantic_stream)
            except Exception:
                logger.exception("Error detaching ACP forwarder subscriber")
        self._semantic_stream = None
        self._target = None

    # ------------------------------------------------------------------
    # Live forwarders
    # ------------------------------------------------------------------

    async def _run_semantic_forwarder(
        self, target: "AcpTransport", recv_stream: Any
    ) -> None:
        """Background task: drain the subscriber stream and forward.

        Each notification has its ``session_id`` rewritten to the
        connection's ``wire_session_id`` before forwarding. The router
        publishes notifications keyed to the target's
        ``LiveAcpTransport.session_id``, but after a picker selection
        the connection's wire id is the synthetic control id — so
        passthroughs would otherwise reach the client with a session
        id they've never seen. The auto-bind / direct loadSession
        paths have wire == target, so the rewrite is a no-op there.

        Per-notification error boundary, split three ways:
        - Transform / rewrite failure (Python-level bug on one
          notification) → WARNING + skip this notification, continue
          the loop (the next one might be fine).
        - Normal-disconnect on send → DEBUG + exit. Every subsequent
          send would fail the same way; the warn-and-continue shape
          would otherwise spam the log on every dropped peer (matters
          more when ``--acp-server`` binds a routable interface).
        - Unexpected send failure → WARNING + exit (connection is
          probably toast).

        Outer stream-iteration failure: normal close logs DEBUG,
        unexpected logs WARNING. ``CancelledError`` propagates
        naturally because it inherits from ``BaseException`` (not
        ``Exception``).
        """
        out: SessionNotification | None = None
        with acp_send_guard("ACP semantic forwarder: stream iteration failed") as outer:
            async for notif in recv_stream:
                # Mark the in-flight window so ``drain`` accounts
                # for this item even though it's no longer counted
                # in the stream's ``current_buffer_used`` (we've
                # already pulled it). Cleared in the same
                # try/finally that bumps the counter.
                self._processing_item = True
                # Track every item we PULL from the stream so the
                # drain barrier counts plan-policy-suppressed items
                # too — the caller only cares that the buffer it
                # snapshotted is empty, not whether each item ended
                # up on the wire vs. dropped.
                try:
                    with acp_guard(
                        "ACP semantic forwarder: transform / rewrite failed "
                        "for one notification; skipping"
                    ) as t:
                        transformed = self._plan_policy.transform(notif)
                        if transformed is None:
                            # plan-policy suppressed this notification
                            out = None
                        else:
                            out = self._rewrite_session_id(transformed)
                    if t.failed or out is None:
                        continue
                    with acp_send_guard("ACP semantic forwarder: send failed") as send:
                        await self._send_session_update(out)
                    if send.should_exit:
                        return
                finally:
                    # Bump the drain-barrier counter and wake any
                    # waiters whether or not the send succeeded —
                    # draining is about "this buffered item has been
                    # processed by the forwarder", not "the wire
                    # accepted it". A failed send means we're about
                    # to exit the loop anyway; waiters watching us
                    # also bail via the ``_semantic_task.done()``
                    # guard in :meth:`drain`. Clear ``_processing_item``
                    # IN THE FINALLY so the drain barrier never sees
                    # the in-flight window cross a yield without
                    # being accounted for.
                    self._notifications_sent += 1
                    self._processing_item = False
                    self._sent_event.set()
                    self._sent_event = anyio.Event()
        if outer.should_exit:
            return
        # Reaching here means the subscriber stream returned EOF —
        # the LiveAcpTransport's ``__aexit__`` ran ``_pubsub.close_all()``
        # because the sample's react loop returned. Signal the client
        # so it can flip its lifecycle pill to ``complete`` even though
        # the underlying transport remains open (the connection is
        # reusable for picker → another sample). The previous design
        # had no positive end-of-session signal, so a client bound to
        # sample 1 wouldn't know sample 1 had finished until either
        # the entire eval ended (transport disconnect) or the client
        # noticed via some other side-effect.
        #
        # Drain the raw-event firehose BEFORE the session_ended
        # notification. The semantic stream closes when the sample
        # exits its react() / finalize() — but raw transcript events
        # from the post-agent scoring phase (``ScoreEvent``,
        # ``SampleLimitEvent``) ride the raw forwarder, not the
        # semantic one. Without this barrier the raw forwarder's
        # task can still have queued items in flight when we send
        # ``inspect/session_ended``, and the client races the wire:
        # the lifecycle terminator can arrive BEFORE the trailing
        # scoring events, dropping them or rendering them after the
        # pill already flipped to ``complete``.
        if self._raw_forwarder is not None:
            await self._raw_forwarder.drain()
        await self._send_session_ended()

    async def _send_session_ended(self) -> None:
        """Notify the client that the bound session has ended on the server.

        Best-effort: a send failure here means the peer is gone
        (which is functionally the same state we're signalling), so
        the ``acp_send_guard`` is sufficient — no caller action
        beyond logging.
        """
        with acp_send_guard("ACP semantic forwarder: session_ended send failed"):
            await self._connection.send_notification(
                INSPECT_SESSION_ENDED_METHOD,
                {"sessionId": self._wire_session_id},
            )

    async def drain(self) -> None:
        """Block until the forwarder has processed all currently-buffered items.

        The approval shim calls this immediately before sending a
        ``session/request_permission`` so the operator sees the
        model's accompanying ``agent_message_chunk`` (rendered as
        an assistant chip in the conversation stream) BEFORE the
        approval card appears on the same connection.

        Without this barrier the wire order can be wrong:
        notifications travel through the in-process pub/sub bus →
        per-connection forwarder task → ``conn.send_notification``;
        the permission request goes via ``conn.send_request``
        directly on the calling task. When the forwarder task
        hasn't been scheduled yet, the request reaches the wire
        before the queued notification, and the operator sees the
        approval card with no "why" context.

        Semantics: yield until every item that was sitting in our
        subscriber stream's buffer AT CALL TIME has been processed.
        Items published AFTER this call don't need to be ordered
        before our caller's next send — they belong AFTER it.

        Safe no-op when the forwarder isn't running (pre-start /
        post-stop / forwarder task already exited). Cancellation
        propagates naturally via the ``Event.wait`` inside the
        loop.
        """
        if (
            self._semantic_stream is None
            or self._semantic_task is None
            or self._semantic_task.done()
        ):
            return
        # Snapshot what the forwarder still has to process:
        # - ``current_buffer_used``: items SITTING in the stream
        #   buffer, not yet pulled by the forwarder loop.
        # - ``_processing_item``: True iff the forwarder has pulled
        #   an item but hasn't reached the ``finally`` block that
        #   bumps the counter. This window is invisible to
        #   ``current_buffer_used`` (the item already left the
        #   buffer) AND to ``_notifications_sent`` (the counter
        #   hasn't bumped yet) — without it, ``drain`` would return
        #   while a pulled-but-not-yet-sent item is still in flight,
        #   defeating the ordering guarantee.
        try:
            buffered = self._semantic_stream.statistics().current_buffer_used
        except Exception:
            # If statistics() ever changes shape under us, fail open
            # — better to skip the barrier than to hang the approval.
            return
        in_flight = 1 if self._processing_item else 0
        pending_to_process = buffered + in_flight
        if pending_to_process == 0:
            return
        target = self._notifications_sent + pending_to_process
        # Loop: check the counter, wait on the per-tick event,
        # re-check. The event is replaced on each tick (so multiple
        # ticks between our wait() returns don't make us miss
        # signals — each loop iteration captures the current event
        # reference before waiting).
        while self._notifications_sent < target:
            if self._semantic_task.done():
                # Forwarder died (peer disconnect / unhandled
                # exception). Stop waiting — the caller's request
                # would fail too, and that's the more useful error.
                return
            await self._sent_event.wait()

    def _rewrite_session_id(self, notif: SessionNotification) -> SessionNotification:
        """Return ``notif`` keyed to the wire sessionId.

        Cheap fast-path: when the notification already carries
        ``wire_session_id`` (auto-bind / direct loadSession cases),
        return it unchanged.

        Uses ``self._wire_session_id`` captured at construction —
        immutable for this Forwarders instance, so live forwarding
        cannot be cross-streamed by a later rebind that updated
        ``self._state.wire_session_id``.
        """
        if notif.session_id == self._wire_session_id:
            return notif
        return notif.model_copy(update={"session_id": self._wire_session_id})

    # ------------------------------------------------------------------
    # Replay-on-attach
    # ------------------------------------------------------------------

    async def _run_replay(self, snapshot: list[Any]) -> SendStatus:
        """Emit recent transcript history out to this connection.

        Single interleaved pass: walk the snapshot in transcript
        (source) order and, for each event, dispatch to whichever
        streams want it — raw firehose if subscribed, semantic
        firehose if it passes the sub-agent filter. Wire ordering
        matches the underlying transcript order, so on a late attach
        score chips appear AFTER the conversation that produced them,
        plan updates land at their original timestamp relative to
        message groups, etc.

        Previously the two streams were two separate passes (raw then
        semantic), which on late attaches made score chips render
        above the replayed conversation and could let a stale
        ``AgentPlanUpdate`` from semantic replay arrive after raw
        replay had already cleared the plan via the scorers boundary.
        The interleaved walk is the structural fix; the
        ``_scoring_started`` state-guard in the TUI is a belt-and-
        braces defense for any straggling ordering bug.

        Both streams are capped to :data:`REPLAY_MAX_EVENTS` (each
        applied to its respective universe — full snapshot for raw,
        sub-agent-filtered snapshot for semantic) so a long-running
        sample doesn't push a multi-MB catch-up payload.

        Uses ``self._wire_session_id`` (captured at construction) for
        semantic notification construction — immutable for this
        Forwarders instance, so the cross-stream race (rebind during
        raw-replay yield → semantic events under new wire id) cannot
        occur. Caller holds ``ConnectionHandler._bind_lock`` so no
        concurrent bind can interleave with this method's awaits.

        Returns a :class:`SendStatus`. ``should_exit`` is True iff a
        send failed (disconnect or otherwise) — :meth:`start` checks
        this, calls :meth:`stop` to detach what's already been
        attached, and returns without launching the live forwarder
        tasks. The underlying ``acp`` library's sender task dies on
        any send failure, so a subsequent live send would enqueue a
        future with no sender left to complete it. We can't wait for
        ``Connection.main_loop`` to exit and trigger outer cleanup
        either: ``acp``'s ``TaskSupervisor`` only logs the dead-task
        failure, it doesn't close the receive loop. The explicit
        :meth:`stop` call in :meth:`start` is what guarantees the
        attached subscribers (semantic pub/sub, raw transcript, and
        approver registration) don't leak.

        Per-step error boundary:
        - Sub-agent filter pre-pass failure → WARNING, fall back to
          raw-only replay (semantic just has no events to map; the
          connection is still fine).
        - Per-notification transform / per-event serialize failure →
          WARNING + skip (next event might be fine; isolated inside
          :class:`ReplayTranscriptor.process` / :meth:`replay_event`).
        - Per-notification send failure → mirror :class:`SendStatus`
          and return.

        ``CancelledError`` propagates naturally (BaseException, not
        Exception).
        """
        # SEMANTIC pre-pass: walk the sub-agent filter once over the
        # full snapshot so we know which events pass. Cap to the last
        # N filtered events, identify them by ``id()`` (event objects
        # are not hashable in general — Pydantic BaseModels are
        # value-equality, two events with the same fields would
        # collide in a set keyed on the object itself).
        semantic_id_set: set[int] = set()
        with acp_guard(
            "ACP semantic replay: sub-agent filter failed; semantic replay skipped"
        ) as f:
            filtered_full = list(_filter_subagent_events(snapshot))
            semantic_id_set = {id(e) for e in filtered_full[-REPLAY_MAX_EVENTS:]}
        if f.failed:
            semantic_id_set = set()

        # Raw cap: last N of the full snapshot.
        raw_id_set: set[int] = (
            {id(e) for e in snapshot[-REPLAY_MAX_EVENTS:]}
            if self._raw_forwarder is not None
            else set()
        )

        # Build a stateful semantic mapper. We feed it ONLY the
        # already-filtered events (in source order) so its
        # depth-tracker + dedup sets advance exactly the way the
        # batch :func:`replay_transcript` would — preserving the
        # same notifications and same per-event ordering. Passing
        # ``filter_subagents=False`` is safe because we already
        # filtered above.
        transcriptor = ReplayTranscriptor(self._wire_session_id, filter_subagents=False)

        # Interleaved dispatch in transcript order.
        for event in snapshot:
            is_raw = id(event) in raw_id_set
            is_semantic = id(event) in semantic_id_set
            if is_raw and self._raw_forwarder is not None:
                with acp_send_guard("ACP raw replay failed") as raw:
                    await self._raw_forwarder.replay_event(event)
                if raw.should_exit:
                    return raw
            if is_semantic:
                for notif in transcriptor.process(event):
                    transformed: SessionNotification | None = None
                    with acp_guard(
                        "ACP semantic replay: plan policy transform failed for "
                        "one notification; skipping"
                    ) as t:
                        transformed = self._plan_policy.transform(notif)
                    if t.failed or transformed is None:
                        continue
                    marked = _stamp_replay_marker(transformed)
                    with acp_send_guard("ACP semantic replay: send failed") as send:
                        await self._send_session_update(marked)
                    if send.should_exit:
                        return send

        return SendStatus()

    # ------------------------------------------------------------------
    # Internal send helper
    # ------------------------------------------------------------------

    async def _send_session_update(self, notification: SessionNotification) -> None:
        """Forward a single notification as ``session/update``.

        ``mode="json"`` matters: notifications can carry ``raw_input``
        / ``_meta`` values that include Python-native types (``Path``,
        ``datetime``, etc.) which Python-mode dump would leave as-is,
        then crash the downstream ``json.dumps`` on the wire. Mirrors
        the handler-side ``_send_session_update`` in ``_connection.py``.
        """
        await self._connection.send_notification(
            _SESSION_UPDATE_METHOD,
            notification.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
