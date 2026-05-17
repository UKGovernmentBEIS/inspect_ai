"""Per-bind outbound forwarder: transcript events → ACP session/update.

The :class:`Forwarders` class owns the lifecycle of a single bind:
attach to a target :class:`AcpSession`'s pub/sub bus + transcript
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
from inspect_ai.agent._acp.event_mapping import SubagentDepthTracker, replay_transcript
from inspect_ai.agent._acp.inspect_ext import (
    PlanPolicyTransformer,
    RawEventForwarder,
)

if TYPE_CHECKING:
    from inspect_ai.agent._acp.connection import ConnectionState
    from inspect_ai.agent._acp.session import AcpSession, ApproverClient

logger = getLogger(__name__)

# Standard ACP method used by the semantic forwarder.
_SESSION_UPDATE_METHOD = CLIENT_METHODS["session_update"]

# ``REPLAY_MAX_EVENTS`` caps replay payload size on late attach so a
# very long-running sample doesn't dump thousands of events on every
# new connection.
REPLAY_MAX_EVENTS = 100


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


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
        *,
        target_session_id: str,
        wire_session_id: str,
    ) -> None:
        self._state = state
        self._connection = connection
        self._approver_client = approver_client
        # IDs captured at construction. Per-bind; immutable for the
        # lifetime of this Forwarders instance. Reading from
        # ``self._state.wire_session_id`` later would be incorrect on
        # rebind paths where the connection's state has moved on but
        # this Forwarders is still draining buffered events.
        self._target_session_id = target_session_id
        self._wire_session_id = wire_session_id
        # Forwarder runtime — populated by ``start()``.
        self._target: "AcpSession | None" = None
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

    async def start(self, target: "AcpSession") -> None:
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
        if self._state.raw_events_enabled:
            self._raw_forwarder = RawEventForwarder(self._connection)
            self._raw_forwarder.attach(target)

        # Register as an approver client so the configured
        # ``human_approver`` can route tool-approval prompts here.
        self._approver_unsub = target.attach_approver_client(self._approver_client)

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

    async def stop(self) -> None:
        """Cancel forwarder tasks + detach subscribers. Idempotent."""
        # Deregister as an approver client so a pending or
        # post-disconnect approval prompt doesn't try to send through
        # a closed connection.
        if self._approver_unsub is not None:
            try:
                self._approver_unsub()
            except Exception:
                logger.exception("Error detaching ACP approver client")
            self._approver_unsub = None
        # Raw forwarder owns its own lifecycle teardown — unsubscribe,
        # close streams, cancel task.
        if self._raw_forwarder is not None:
            await self._raw_forwarder.stop()
            self._raw_forwarder = None
        if self._semantic_task is not None and not self._semantic_task.done():
            self._semantic_task.cancel()
            try:
                await self._semantic_task
            except (anyio.get_cancelled_exc_class(), Exception):
                pass
        self._semantic_task = None
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
        self, target: "AcpSession", recv_stream: Any
    ) -> None:
        """Background task: drain the subscriber stream and forward.

        Each notification has its ``session_id`` rewritten to the
        connection's ``wire_session_id`` before forwarding. The router
        publishes notifications keyed to the target's
        ``LiveAcpSession.session_id``, but after a picker selection
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
        if outer.should_exit:
            return

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

        Two sub-passes (raw first if enabled, then semantic) so the
        client sees the full firehose for catch-up before semantic
        notifications start. Both passes are capped to
        :data:`REPLAY_MAX_EVENTS` to bound the payload on late attaches
        into long-running samples. No transforms beyond plan-policy and
        sub-agent filtering — replay produces the same wire payloads as
        live, so a client that handles live also handles replay.

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
        - Raw replay send failure → mirror :class:`SendStatus` and
          return early; caller (start) skips live forwarders.
        - Sub-agent filter pre-pass failure → WARNING, return a
          non-exit status (we just have no events to map; the
          connection is fine).
        - Per-notification transform failure → WARNING + skip (next
          notif might be fine).
        - Per-notification send failure → mirror :class:`SendStatus`
          and return.

        ``CancelledError`` propagates naturally (BaseException, not
        Exception).
        """
        # RAW replay (opt-in only). Send all transcript events (no
        # sub-agent filter) capped to the last N. Exit replay entirely
        # on EITHER disconnect or unexpected send failure — the
        # underlying ``acp`` library's sender task dies on either kind
        # of failure, so a subsequent semantic send would enqueue a
        # future with no sender to complete it.
        if self._raw_forwarder is not None:
            with acp_send_guard("ACP raw replay failed") as raw:
                await self._raw_forwarder.replay(snapshot, REPLAY_MAX_EVENTS)
            if raw.should_exit:
                return raw

        # SEMANTIC replay. Apply the same sub-agent filter the live
        # router uses. Take the last N events post-filter, then map to
        # SessionNotifications using the captured wire id, then apply
        # plan policy. Per-event mapping isolation lives inside
        # ``replay_transcript`` itself — one bad event no longer drops
        # the rest of the replay.
        filtered: list[Any] = []
        with acp_guard(
            "ACP semantic replay: sub-agent filter failed; skipping replay"
        ) as f:
            filtered = list(_filter_subagent_events(snapshot))[-REPLAY_MAX_EVENTS:]
        if f.failed:
            # Filter failure doesn't kill the connection; just return a
            # non-exit status so live forwarders still launch.
            return SendStatus()

        for notif in replay_transcript(
            filtered,
            self._wire_session_id,
            filter_subagents=False,  # already pre-filtered
        ):
            transformed: SessionNotification | None = None
            with acp_guard(
                "ACP semantic replay: plan policy transform failed for "
                "one notification; skipping"
            ) as t:
                transformed = self._plan_policy.transform(notif)
            if t.failed or transformed is None:
                continue
            with acp_send_guard("ACP semantic replay: send failed") as send:
                await self._send_session_update(transformed)
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
