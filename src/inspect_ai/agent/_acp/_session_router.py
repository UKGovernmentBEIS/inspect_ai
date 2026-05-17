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
import json
import math
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, Iterator

import anyio
from acp.connection import Connection
from acp.helpers import plan_entry, session_notification, update_plan
from acp.meta import CLIENT_METHODS
from acp.schema import (
    SessionNotification,
    ToolCallProgress,
    ToolCallStart,
)

from inspect_ai.agent._acp._router import SubagentDepthTracker, replay_transcript

if TYPE_CHECKING:
    from inspect_ai.agent._acp._connection import ConnectionState
    from inspect_ai.agent._acp._session import AcpSession, ApproverClient

logger = getLogger(__name__)

# JSON-RPC method names. ``session/update`` is the standard ACP method
# the semantic forwarder uses; ``inspect/event`` is the non-standard
# raw-event notification opted into via ``inspect.raw_events`` capability.
_SESSION_UPDATE_METHOD = CLIENT_METHODS["session_update"]
_RAW_EVENT_METHOD = "inspect/event"

# Tool names whose invocations translate to ACP's ``AgentPlanUpdate``
# for plan-capable clients. Hard-coded by tool name (matches Inspect's
# first-party planning tools — see ``tool/_tools/_update_plan.py`` and
# ``tool/_tools/_todo_write.py``).
PLAN_TOOL_NAMES = frozenset({"update_plan", "todo_write"})

# Replay parameters (hard-coded; configurable later).
# ``REPLAY_MAX_EVENTS`` caps replay payload size on late attach so a
# very long-running sample doesn't dump thousands of events on every
# new connection. ``ELISION_THRESHOLD_BYTES`` truncates oversized
# tool-call arguments / results during replay (the user can still see
# WHAT tool ran; the inline data is replaced with an elision marker if
# it'd flood the wire).
REPLAY_MAX_EVENTS = 100
ELISION_THRESHOLD_BYTES = 4096


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


def _elided_marker(size_bytes: int) -> dict[str, Any]:
    """Build the standard elision marker dict."""
    return {"_inspect.elided": True, "_inspect.original_size": size_bytes}


def _maybe_elide(value: Any, threshold: int) -> Any:
    """Return an elision marker if ``value`` serializes to more than ``threshold`` bytes.

    Pass-through otherwise (including for ``None``, which doesn't
    contribute size). Serialization uses ``json.dumps(..., default=str)``
    so non-JSON-native types still get sized (best-effort).
    """
    if value is None:
        return None
    try:
        size = len(json.dumps(value, default=str))
    except Exception:
        return value
    if size > threshold:
        return _elided_marker(size)
    return value


def _elide_tool_call_notification(
    notif: SessionNotification, threshold: int
) -> SessionNotification:
    """Return ``notif`` with oversized raw_input/raw_output elided.

    Only affects ``ToolCallStart`` / ``ToolCallProgress`` payloads.
    Returns the original notification untouched for any other update
    variant. Uses ``model_copy(update=...)`` so the original is not
    mutated.
    """
    update = notif.update
    if not isinstance(update, (ToolCallStart, ToolCallProgress)):
        return notif
    new_raw_input = _maybe_elide(update.raw_input, threshold)
    new_raw_output = _maybe_elide(update.raw_output, threshold)
    if new_raw_input is update.raw_input and new_raw_output is update.raw_output:
        return notif
    new_update = update.model_copy(
        update={"raw_input": new_raw_input, "raw_output": new_raw_output}
    )
    return notif.model_copy(update={"update": new_update})


def _elide_raw_event_payload(payload: dict[str, Any], threshold: int) -> None:
    """In-place elide oversized fields on a serialized transcript event payload.

    Currently targets ToolEvent's ``arguments`` and ``result`` fields
    (the most likely sources of huge inline blobs). ModelEvent's
    ``call`` field is left alone — large model-call payloads are
    handled by the log-writer's attachment-extraction step, but the
    raw forwarder sees them before that extraction (and consumers
    explicitly opted in for the firehose).

    Mutates ``payload`` in place since the caller built it via
    ``model_dump`` specifically for sending.
    """
    if payload.get("event") != "tool":
        return
    for key in ("arguments", "result"):
        if key in payload:
            payload[key] = _maybe_elide(payload[key], threshold)


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
    ) -> None:
        self._state = state
        self._connection = connection
        self._approver_client = approver_client
        # Forwarder runtime — populated by ``start()``.
        self._target: "AcpSession | None" = None
        self._semantic_stream: Any = None
        self._semantic_task: asyncio.Task[None] | None = None
        # Raw event forwarder runtime (opt-in via ``inspect.raw_events``).
        # The send/receive pair bridges the sync transcript subscriber
        # callback into the async forwarder task.
        self._raw_send: Any = None
        self._raw_recv: Any = None
        self._raw_task: asyncio.Task[None] | None = None
        self._raw_unsubscribe: Callable[[], None] | None = None
        # Approver client unsubscribe callable.
        self._approver_unsub: Callable[[], None] | None = None
        # Per-tool stash for plan-policy transformation. Plan-capable
        # clients suppress the in-progress ToolCallStart for plan tools;
        # we remember raw_input + title here so when the matching
        # ToolCallProgress arrives (no raw_input on its own), we can
        # build the AgentPlanUpdate from the original arguments. Cleared
        # per tool on emit, and structurally fresh on each bind.
        self._plan_tool_stash: dict[str, dict[str, Any]] = {}

    async def start(self, target: "AcpSession", target_session_id: str) -> None:
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
        """
        self._target = target

        # SNAPSHOT (sync) — captures everything that's happened so far.
        snapshot = list(target.transcript_events_snapshot())

        # ATTACH live subscribers (also sync) — from here on new events
        # go into the live buffers, not the snapshot.
        self._semantic_stream = target.attach()
        if self._state.raw_events_enabled:
            self._raw_send, self._raw_recv = anyio.create_memory_object_stream[Any](
                max_buffer_size=math.inf
            )
            self._raw_unsubscribe = target.subscribe_transcript_events(
                self._on_raw_event
            )

        # Register as an approver client so the configured
        # ``human_approver`` can route tool-approval prompts here.
        self._approver_unsub = target.attach_approver_client(self._approver_client)

        # REPLAY — emit historical notifications synchronously before
        # live ones. Raw replay (if enabled) first, then semantic.
        await self._run_replay(snapshot)

        # LIVE forwarders — drain the buffers that have been filling
        # since attach.
        self._semantic_task = asyncio.create_task(
            self._run_semantic_forwarder(target, self._semantic_stream),
            name=f"acp-fwd-semantic-{target_session_id}",
        )
        if self._state.raw_events_enabled:
            self._raw_task = asyncio.create_task(
                self._run_raw_forwarder(self._raw_recv),
                name=f"acp-fwd-raw-{target_session_id}",
            )

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
        # Unsubscribe from the transcript first so no more raw events
        # land in the queue while we're tearing down.
        if self._raw_unsubscribe is not None:
            try:
                self._raw_unsubscribe()
            except Exception:
                logger.exception("Error unsubscribing ACP raw forwarder")
            self._raw_unsubscribe = None
        if self._raw_send is not None:
            try:
                self._raw_send.close()
            except Exception:
                pass
            self._raw_send = None
        for task in (self._semantic_task, self._raw_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (anyio.get_cancelled_exc_class(), Exception):
                    pass
        self._semantic_task = None
        self._raw_task = None
        if self._target is not None and self._semantic_stream is not None:
            try:
                self._target.detach(self._semantic_stream)
            except Exception:
                logger.exception("Error detaching ACP forwarder subscriber")
        self._semantic_stream = None
        if self._raw_recv is not None:
            try:
                self._raw_recv.close()
            except Exception:
                pass
            self._raw_recv = None
        self._target = None
        # Plan-tool stash is keyed by tool_call_id and is meaningful only
        # for the current bind. Clearing here belt-and-suspenders against
        # an unexpected restart-on-same-Forwarders path; the structural
        # guarantee (fresh Forwarders per bind) is what's load-bearing.
        self._plan_tool_stash.clear()

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
        """
        try:
            async for notif in recv_stream:
                out = self._maybe_transform_plan_tool(notif)
                if out is None:
                    continue  # plan-policy suppressed this notification
                out = self._rewrite_session_id(out)
                await self._send_session_update(out)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            logger.exception("ACP semantic forwarder failed")

    def _rewrite_session_id(self, notif: SessionNotification) -> SessionNotification:
        """Return ``notif`` keyed to the wire sessionId.

        Cheap fast-path: when the notification already carries
        ``wire_session_id`` (auto-bind / direct loadSession cases),
        return it unchanged.
        """
        if (
            self._state.wire_session_id is None
            or notif.session_id == self._state.wire_session_id
        ):
            return notif
        return notif.model_copy(update={"session_id": self._state.wire_session_id})

    def _on_raw_event(self, event: Any) -> None:
        """Sync transcript subscriber callback. Snapshots + enqueues for the forwarder.

        Serializes the event **here** rather than in the forwarder task
        because the subscriber callback runs BEFORE
        ``Transcript._process_event``'s attachment-extraction step
        (``walk_model_call`` reassigns ``event.call`` to an
        attachment-ref form). If we enqueued just the event reference
        and serialized later, by the time the forwarder task picked it
        up the inline ``call`` payload would already be gone. Doing
        ``model_dump`` here captures the pre-condensation state.

        Non-blocking via ``send_nowait``; dead send half is dropped
        (the forwarder cleanup runs first on disconnect, so a closed
        stream here is an expected race).
        """
        if self._raw_send is None:
            return
        try:
            payload = event.model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception:
            logger.exception(
                "ACP raw event subscriber: event failed to serialize; skipping"
            )
            return
        try:
            self._raw_send.send_nowait(payload)
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass

    async def _run_raw_forwarder(self, recv_stream: Any) -> None:
        """Background task: drain serialized raw events out as inspect/event."""
        try:
            async for payload in recv_stream:
                await self._connection.send_notification(_RAW_EVENT_METHOD, payload)
        except anyio.get_cancelled_exc_class():
            raise
        except Exception:
            logger.exception("ACP raw forwarder failed")

    # ------------------------------------------------------------------
    # Plan policy
    # ------------------------------------------------------------------

    def _maybe_transform_plan_tool(
        self, notif: SessionNotification
    ) -> SessionNotification | None:
        """Apply the per-connection plan-policy transformation.

        For plan-capable clients (``state.client_renders_plan``):
        - ToolCallStart for a plan tool with ``status="in_progress"``:
          stash raw_input + title for later use; suppress (return None).
        - ToolCallStart for a plan tool with terminal status (e.g.
          ``status="completed"`` — instant-complete case): build and
          return the ``AgentPlanUpdate`` directly.
        - ToolCallProgress for a previously-stashed plan tool: build
          and return the ``AgentPlanUpdate`` using the stashed input,
          then clear the stash.
        - Any other notification: passthrough.

        Non-plan-capable clients always passthrough.
        """
        if not self._state.client_renders_plan:
            return notif

        update = notif.update
        if isinstance(update, ToolCallStart):
            title = update.title or ""
            if title not in PLAN_TOOL_NAMES:
                return notif
            self._plan_tool_stash[update.tool_call_id] = {
                "title": title,
                "raw_input": update.raw_input,
            }
            if update.status == "in_progress":
                return None
            stash = self._plan_tool_stash.pop(update.tool_call_id, None)
            if stash is None:
                return notif
            plan = self._build_plan_update(stash["title"], stash["raw_input"])
            return plan if plan is not None else notif

        if isinstance(update, ToolCallProgress):
            stash = self._plan_tool_stash.pop(update.tool_call_id, None)
            if stash is None:
                return notif
            plan = self._build_plan_update(stash["title"], stash["raw_input"])
            return plan if plan is not None else notif

        return notif

    def _build_plan_update(
        self, title: str, raw_input: Any
    ) -> SessionNotification | None:
        """Translate a plan-tool's raw_input into an AgentPlanUpdate notification.

        Returns ``None`` if the raw_input shape doesn't match what the
        named tool expects (the forwarder falls back to passthrough in
        that case). Defaults ``priority="medium"`` since neither
        ``update_plan`` nor ``todo_write`` carry priority.
        """
        if not isinstance(raw_input, dict) or self._state.wire_session_id is None:
            return None
        if title == "update_plan":
            items = raw_input.get("plan")
            content_key = "step"
        elif title == "todo_write":
            items = raw_input.get("todos")
            content_key = "content"
        else:
            return None
        if not isinstance(items, list):
            return None
        entries = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entries.append(
                plan_entry(
                    str(item.get(content_key, "")),
                    status=item.get("status", "pending"),
                    priority="medium",
                )
            )
        return session_notification(self._state.wire_session_id, update_plan(entries))

    # ------------------------------------------------------------------
    # Replay-on-attach
    # ------------------------------------------------------------------

    async def _run_replay(self, snapshot: list[Any]) -> None:
        """Emit recent transcript history out to this connection.

        Two sub-passes (raw first if enabled, then semantic) so the
        client sees the full firehose for catch-up before semantic
        notifications start. Both passes are capped to
        :data:`REPLAY_MAX_EVENTS` to bound the payload on late attaches
        into long-running samples.

        Tool-call raw_input / raw_output (semantic notifications) and
        ToolEvent arguments / result (raw events) are elided when their
        JSON-serialized size exceeds :data:`ELISION_THRESHOLD_BYTES`,
        replaced with ``{"_inspect.elided": true,
        "_inspect.original_size": N}``. Live forwarding does NOT elide.
        """
        if self._state.wire_session_id is None:
            return

        # RAW replay (opt-in only). Send all transcript events (no
        # sub-agent filter) capped to the last N. Elide tool-event
        # arguments / result on the serialized payload.
        if self._state.raw_events_enabled:
            raw_events = snapshot[-REPLAY_MAX_EVENTS:]
            for event in raw_events:
                try:
                    payload = event.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    )
                except Exception:
                    logger.exception(
                        "ACP raw replay: event failed to serialize; skipping"
                    )
                    continue
                _elide_raw_event_payload(payload, ELISION_THRESHOLD_BYTES)
                await self._connection.send_notification(_RAW_EVENT_METHOD, payload)

        # SEMANTIC replay. Apply the same sub-agent filter the live
        # router uses. Take the last N events post-filter, then map to
        # SessionNotifications, then apply plan policy + elision.
        filtered = list(_filter_subagent_events(snapshot))[-REPLAY_MAX_EVENTS:]
        notifications = list(
            replay_transcript(
                filtered,
                self._state.wire_session_id,
                filter_subagents=False,  # already pre-filtered
            )
        )
        for notif in notifications:
            transformed = self._maybe_transform_plan_tool(notif)
            if transformed is None:
                continue
            elided = _elide_tool_call_notification(transformed, ELISION_THRESHOLD_BYTES)
            await self._send_session_update(elided)

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
