"""In-process event router for live ACP sessions.

When a :class:`_LiveAcpSession` is active, an ``_AcpEventRouter`` is
attached at session entry. It subscribes to the active sample's
``Transcript`` and:

1. Tracks ``SpanBeginEvent(type=AGENT_SPAN_TYPE)`` / ``SpanEndEvent`` pairs
   to maintain a sub-agent nesting depth counter.
2. Optionally filters out events emitted while a sub-agent boundary is
   open (default ACP-friendly behavior; consumers can opt out via
   :meth:`_LiveAcpSession.disable_subagent_filtering`).
3. Maps the surviving events to ``acp.SessionNotification`` payloads
   and publishes them onto the session's pub/sub bus.

Phase 6 maps only :class:`ModelEvent` (text + reasoning blocks) and
:class:`ToolEvent` (start + post-completion update). Other transcript
event types — :class:`InfoEvent`, :class:`CompactionEvent`,
:class:`InterruptEvent`, state changes, etc. — are silently dropped.
Mapping the Inspect-native event family onto ACP's ``_meta`` extension
is deferred to Phase 8+ where the ``initialize`` handshake provides a
proper capability-negotiation path for clients to opt in.

Phase 10 adds :func:`replay_transcript` — a stateless module-level
helper that takes a list of past transcript events and yields the
session notifications they map to (with the same sub-agent filter and
de-dup semantics as the live router). Used by Phase 10's
replay-on-attach path so late-joining clients see recent transcript
context before live updates start.
"""

from __future__ import annotations

from collections.abc import Sequence
from logging import getLogger
from typing import TYPE_CHECKING, Callable, Iterator, Literal

from acp.helpers import (
    session_notification,
    start_tool_call,
    text_block,
    update_agent_message,
    update_agent_thought,
    update_tool_call,
)
from acp.schema import SessionNotification

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.util._span import AGENT_SPAN_TYPE

if TYPE_CHECKING:
    from inspect_ai.agent._acp._session import _LiveAcpSession

logger = getLogger(__name__)

_ToolCallStatus = Literal["pending", "in_progress", "completed", "failed"]


class _AcpEventRouter:
    """Subscribe to a transcript, map events, publish session notifications."""

    def __init__(self, session: "_LiveAcpSession") -> None:
        self._session = session
        self._sub_agent_depth: int = 0
        self._boundary_span_ids: set[str] = set()
        self._seen_tool_call_ids: set[str] = set()
        # ModelEvent uuids we've already emitted chunks for. The
        # generate flow records the event twice — once pending=True at
        # call time, again as pending=None when `complete()` fires — and
        # cache hits skip the pending phase entirely (the event is born
        # non-pending and is then re-touched by complete()). De-duping
        # by uuid keeps either flow at exactly one chunk emission.
        self._seen_model_event_ids: set[str] = set()
        self._unsubscribe: Callable[[], None] | None = None

    def attach(self) -> None:
        """Subscribe to the active transcript. Idempotent (re-attach is a no-op)."""
        if self._unsubscribe is not None:
            return
        self._unsubscribe = transcript()._add_subscriber(self._process)

    def detach(self) -> None:
        """Unsubscribe from the transcript. Idempotent."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _process(self, event: Event) -> None:
        # Boundary depth tracking. We pair span begin/end by id so an
        # arbitrary out-of-order or unknown SpanEndEvent (e.g. one that
        # opened before the router attached) doesn't underflow.
        if isinstance(event, SpanBeginEvent) and event.type == AGENT_SPAN_TYPE:
            self._boundary_span_ids.add(event.id)
            self._sub_agent_depth += 1
            return
        if isinstance(event, SpanEndEvent) and event.id in self._boundary_span_ids:
            self._boundary_span_ids.discard(event.id)
            self._sub_agent_depth -= 1
            return

        if self._sub_agent_depth > 0 and self._session._filter_subagent_events:
            return

        for notification in _map_event(
            event,
            self._session.session_id,
            self._seen_tool_call_ids,
            self._seen_model_event_ids,
        ):
            self._session.publish(notification)


def replay_transcript(
    events: Sequence[Event],
    session_id: str,
    *,
    filter_subagents: bool = True,
) -> Iterator[SessionNotification]:
    """Map a sequence of past transcript events to session notifications.

    Standalone version of :meth:`_AcpEventRouter._process` for the
    Phase 10 replay-on-attach path. Each call gets fresh depth-tracking
    and dedup state — there is no shared state with the live router,
    so a replay run does not interfere with live event publication.

    By default applies the same sub-agent depth filter the live router
    uses; pass ``filter_subagents=False`` to include events emitted
    inside sub-agent spans (useful for the raw-event firehose where
    callers explicitly opted in for full visibility).
    """
    sub_agent_depth = 0
    boundary_span_ids: set[str] = set()
    seen_tool_call_ids: set[str] = set()
    seen_model_event_ids: set[str] = set()

    for event in events:
        if isinstance(event, SpanBeginEvent) and event.type == AGENT_SPAN_TYPE:
            boundary_span_ids.add(event.id)
            sub_agent_depth += 1
            continue
        if isinstance(event, SpanEndEvent) and event.id in boundary_span_ids:
            boundary_span_ids.discard(event.id)
            sub_agent_depth -= 1
            continue

        if sub_agent_depth > 0 and filter_subagents:
            continue

        yield from _map_event(
            event, session_id, seen_tool_call_ids, seen_model_event_ids
        )


def _map_event(
    event: Event,
    session_id: str,
    seen_tool_call_ids: set[str],
    seen_model_event_ids: set[str],
) -> Iterator[SessionNotification]:
    """Map a single event to zero-or-more session notifications.

    Shared by the live router (which threads its own dedup sets per
    session) and the replay helper (which uses one-shot local sets).
    """
    if isinstance(event, ModelEvent):
        yield from _map_model_event(event, session_id, seen_model_event_ids)
    elif isinstance(event, ToolEvent):
        yield from _map_tool_event(event, session_id, seen_tool_call_ids)


def _map_model_event(
    event: ModelEvent,
    session_id: str,
    seen_model_event_ids: set[str],
) -> Iterator[SessionNotification]:
    # Drop pending/empty events — we emit one chunk per completed
    # text/reasoning block, so there's nothing to publish until the
    # model returns. The pending → completed transition triggers a
    # second _process call via _event_updated.
    if event.pending or event.output.empty:
        return
    # De-dup by uuid: complete() calls _event_updated on the same
    # event after its initial _event, and cache hits emit a non-pending
    # event then call complete() on the same instance — both paths
    # would otherwise double-publish the same chunks.
    uuid = event.uuid
    if uuid is not None:
        if uuid in seen_model_event_ids:
            return
        seen_model_event_ids.add(uuid)
    message = event.output.message
    if not isinstance(message.content, list):
        if message.text:
            yield session_notification(
                session_id,
                update_agent_message(text_block(message.text)),
            )
        return
    for block in message.content:
        if isinstance(block, ContentText) and block.text:
            yield session_notification(
                session_id,
                update_agent_message(text_block(block.text)),
            )
        elif isinstance(block, ContentReasoning):
            # For redacted reasoning, `block.reasoning` may carry the
            # provider's encrypted/redacted payload — only `summary`
            # is display-safe. Mirror ContentReasoning.text's policy
            # (`self.reasoning if not self.redacted else (self.summary or "")`).
            reasoning_text = (
                (block.summary or "") if block.redacted else block.reasoning
            )
            yield session_notification(
                session_id,
                update_agent_thought(text_block(reasoning_text)),
            )


def _map_tool_event(
    event: ToolEvent,
    session_id: str,
    seen_tool_call_ids: set[str],
) -> Iterator[SessionNotification]:
    status = _tool_call_status(event)
    if event.id in seen_tool_call_ids:
        yield session_notification(
            session_id,
            update_tool_call(tool_call_id=event.id, status=status),
        )
    else:
        seen_tool_call_ids.add(event.id)
        # Populate `raw_input` so downstream consumers can read tool
        # arguments directly. The Phase 10 plan-policy forwarder uses
        # this to translate `update_plan` / `todo_write` invocations
        # into `AgentPlanUpdate` notifications without re-fetching from
        # the original transcript event.
        yield session_notification(
            session_id,
            start_tool_call(
                tool_call_id=event.id,
                title=event.function,
                status=status,
                raw_input=event.arguments,
            ),
        )


def _tool_call_status(event: ToolEvent) -> _ToolCallStatus:
    if event.pending:
        return "in_progress"
    if event.error is not None or event.failed:
        return "failed"
    return "completed"
