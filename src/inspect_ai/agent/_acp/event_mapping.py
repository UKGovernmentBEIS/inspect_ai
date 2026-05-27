"""Transcript-event → ACP-notification mapping.

Distinct from :mod:`.session_router`, which forwards already-mapped
notifications out over a bound connection. This module is the
in-process step before that — transcript events become typed
``acp.SessionNotification`` payloads on the session's pub/sub bus.

When a :class:`LiveAcpTransport` is active, an :class:`_AcpEventRouter`
is attached at session entry. It subscribes to the active sample's
``Transcript`` and:

1. Tracks ``SpanBeginEvent(type=AGENT_SPAN_TYPE)`` / ``SpanEndEvent`` pairs
   to maintain a sub-agent nesting depth counter.
2. Optionally filters out events emitted while a sub-agent boundary is
   open (default ACP-friendly behavior; consumers can opt out via
   :meth:`LiveAcpTransport.disable_subagent_filtering`).
3. Maps the surviving events to ``acp.SessionNotification`` payloads
   and publishes them onto the session's pub/sub bus.

Maps only :class:`ModelEvent` (text + reasoning blocks) and
:class:`ToolEvent` (start + post-completion update). Other transcript
event types — :class:`InfoEvent`, :class:`CompactionEvent`,
:class:`InterruptEvent`, state changes, etc. — are silently dropped.
Mapping the Inspect-native event family onto ACP's ``_meta`` extension
is a follow-on once a client capability flag exists for it.

:func:`replay_transcript` is a stateless module-level helper that takes
a list of past transcript events and yields the session notifications
they map to (with the same sub-agent filter and de-dup semantics as
the live router). Used by the replay-on-attach path so late-joining
clients see recent transcript context before live updates start.

Tool-call rendering (titles, kind mapping, view / result content
blocks, file-edit diffs) lives in :mod:`.tool_content` so the approval
shim can reuse it without pulling in the live router's transcript
subscription.
"""

from __future__ import annotations

import uuid as _uuid_module
from collections.abc import Sequence
from logging import getLogger
from typing import TYPE_CHECKING, Callable, Iterator, Literal

from acp.helpers import (
    session_notification,
    start_tool_call,
    text_block,
    update_tool_call,
)
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    SessionNotification,
    UsageUpdate,
    UserMessageChunk,
)

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent._acp.inspect_ext import (
    TOTAL_MESSAGES_META_KEY,
    assistant_complete_chunk_meta,
    assistant_content_chunk_meta,
    assistant_pending_chunk_meta,
    input_message_chunk_meta,
)
from inspect_ai.agent._acp.tool_content import (
    _content_for_start,
    _content_for_update,
    _descriptive_title,
    _tool_kind_for,
)
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._model_info import get_model_info
from inspect_ai.util._span import AGENT_SPAN_TYPE

if TYPE_CHECKING:
    from inspect_ai.agent._acp.transport_live import LiveAcpTransport

logger = getLogger(__name__)

_ToolCallStatus = Literal["pending", "in_progress", "completed", "failed"]

_SubagentAction = Literal["consume", "skip", "emit"]


class SubagentDepthTracker:
    """Track depth into sub-agent boundary spans for event filtering.

    Sub-agent invocations (``@agent``-decorated functions called via
    ``run()`` / ``as_tool()`` / ``handoff()`` / ``task_tool``) open a
    ``SpanBeginEvent(type=AGENT_SPAN_TYPE)`` and close it with the
    matching ``SpanEndEvent``. Events emitted **between** the two are
    considered "inside a sub-agent" and the ACP semantic forwarder
    drops them so the editor sees only the outermost conversation.

    The *first* ``AGENT_SPAN_TYPE`` begin we see is treated specially:
    it's the OUTER agent boundary (the eval framework's ``as_solver``
    wrap, or the top-level ``run()`` of a free-standing agent). Its
    contents are exactly the conversation we want to expose, so the
    tracker consumes the boundary markers but keeps depth at 0 for
    everything inside. Only the SECOND ``AGENT_SPAN_TYPE`` begin (a
    real sub-agent nested in the outer one) increments depth.

    This matters because the ACP router attaches at
    ``acp_session().__aenter__`` — which runs BEFORE the solver opens
    the outer ``AGENT_SPAN``. So both LIVE event processing and
    REPLAY-on-attach (whose snapshot starts at the router's
    attach-index) observe the outer span begin. Without the
    "first-is-outer" rule, depth would spike to 1 the moment the
    outer span opens and every subsequent event — the entire
    conversation — would be silently filtered.

    Boundary spans are paired by id so out-of-order or unknown
    ``SpanEndEvent``s (e.g. one that opened before the tracker was
    constructed) don't underflow the counter.

    Used by:
    - :class:`_AcpEventRouter` (live event publication)
    - :func:`replay_transcript` (replay-on-attach with filter param)
    - :func:`inspect_ai.agent._acp.session_router._filter_subagent_events`
      (snapshot pre-filter for replay)
    """

    def __init__(self) -> None:
        self._depth: int = 0
        # ``AGENT_SPAN_TYPE`` ids we treat as in-scope boundaries:
        # the outer agent span (consumed without depth change) plus
        # any nested sub-agent spans (which DO change depth).
        self._boundary_span_ids: set[str] = set()
        # Id of the outer agent span — the one whose contents we
        # surface to the wire. Set on the first
        # ``SpanBeginEvent(type=AGENT_SPAN_TYPE)`` we see; its
        # matching SpanEndEvent is consumed without decrementing
        # depth.
        self._outer_span_id: str | None = None

    @property
    def depth(self) -> int:
        """Current nesting depth (0 = at top level / inside outer agent)."""
        return self._depth

    def process(self, event: Event) -> _SubagentAction:
        """Classify ``event`` and update internal depth state.

        Returns:
        - ``"consume"`` — the event is a boundary marker; the caller
          should NOT emit it (it's bookkeeping).
        - ``"skip"`` — the event was emitted inside a sub-agent; the
          caller should drop it if filtering is enabled.
        - ``"emit"`` — the event is top-level and should be emitted.
        """
        if isinstance(event, SpanBeginEvent) and event.type == AGENT_SPAN_TYPE:
            self._boundary_span_ids.add(event.id)
            if self._outer_span_id is None:
                # First agent span we've seen — this IS the outer
                # agent. Keep depth at 0 so its contents emit.
                self._outer_span_id = event.id
                return "consume"
            self._depth += 1
            return "consume"
        if isinstance(event, SpanEndEvent) and event.id in self._boundary_span_ids:
            self._boundary_span_ids.discard(event.id)
            if event.id == self._outer_span_id:
                # Closing the outer agent — don't decrement (we
                # never incremented for it).
                return "consume"
            self._depth -= 1
            return "consume"
        return "skip" if self._depth > 0 else "emit"


class _AcpEventRouter:
    """Subscribe to a transcript, map events, publish session notifications."""

    def __init__(self, session: "LiveAcpTransport") -> None:
        self._session = session
        self._depth_tracker = SubagentDepthTracker()
        self._seen_tool_call_ids: set[str] = set()
        # ModelEvent uuids we've already emitted chunks for. The
        # generate flow records the event twice — once pending=True at
        # call time, again as pending=None when `complete()` fires — and
        # cache hits skip the pending phase entirely (the event is born
        # non-pending and is then re-touched by complete()). De-duping
        # by uuid keeps either flow at exactly one chunk emission.
        self._seen_model_event_ids: set[str] = set()
        # ModelEvent uuids we've already emitted a pending signal for.
        # Distinct from `_seen_model_event_ids` so the pending → completed
        # transition can still publish real chunks for the same uuid.
        self._seen_pending_event_ids: set[str] = set()
        # ChatMessage ids (system + user) we've already emitted as a
        # UserMessageChunk. On every ModelEvent we walk ``event.input``
        # backwards to the previous assistant turn and publish the
        # messages in between — but the same user prompt sticks
        # around in every subsequent call's input, so per-id dedup is
        # what keeps it from being emitted twice.
        self._seen_user_message_ids: set[str] = set()
        self._unsubscribe: Callable[[], None] | None = None

    def attach(self) -> None:
        """Subscribe to the active transcript. Idempotent (re-attach is a no-op)."""
        if self._unsubscribe is not None:
            return
        tr = transcript()
        # Record the transcript size NOW so late-attach replay can skip
        # pre-acp_session events (sample init, eval framework's outer
        # AGENT_SPAN begin). The live router doesn't observe those —
        # replay needs to mirror that view or the depth filter wipes
        # out every in-scope event downstream.
        self._session._router_attach_index = len(tr.events)
        self._unsubscribe = tr._subscribe(self._process)

    def detach(self) -> None:
        """Unsubscribe from the transcript. Idempotent."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _process(self, event: Event) -> None:
        action = self._depth_tracker.process(event)
        if action == "consume":
            return
        if action == "skip" and self._session._filter_subagent_events:
            return

        for notification in _map_event(
            event,
            self._session.session_id,
            self._seen_tool_call_ids,
            self._seen_model_event_ids,
            self._seen_pending_event_ids,
            self._seen_user_message_ids,
        ):
            self._session.publish(notification)


class ReplayTranscriptor:
    """Stateful per-event mapper: same semantics as :func:`replay_transcript`.

    Holds the depth tracker + dedup id sets so callers can feed events
    one at a time and still get the same notifications, in the same
    order, as the batch generator would produce. The point of
    exposing this per-event entry-point is interleaving: the
    raw-event firehose and the semantic firehose both replay over the
    same transcript snapshot, and on a late attach the wire ordering
    matters (score chips need to appear AFTER the conversation that
    produced them, not above it). Walking events in source order with
    both streams dispatching from the same loop preserves that.

    Construct one instance per replay pass — fresh state per call,
    no shared state with the live router. Mirror the cancellation
    semantics of :func:`replay_transcript`: per-event ``except
    Exception`` only, so ``CancelledError`` propagates.
    """

    def __init__(self, session_id: str, *, filter_subagents: bool = True) -> None:
        self._session_id = session_id
        self._filter_subagents = filter_subagents
        self._tracker = SubagentDepthTracker()
        self._seen_tool_call_ids: set[str] = set()
        self._seen_model_event_ids: set[str] = set()
        self._seen_pending_event_ids: set[str] = set()
        self._seen_user_message_ids: set[str] = set()

    def process(self, event: Event) -> list[SessionNotification]:
        """Map one event to its session notifications.

        Returns ``[]`` for events that the depth tracker consumes
        (span markers) or skips (sub-agent events when filtered).
        Per-event error boundary mirrors :func:`replay_transcript` —
        depth-tracker / mapper failures log a warning and yield
        ``[]`` for that event, keeping the surrounding replay alive.
        """
        try:
            action = self._tracker.process(event)
        except Exception:
            logger.warning(
                "ACP replay: depth tracker failed on one event; skipping",
                exc_info=True,
            )
            return []
        if action == "consume":
            return []
        if action == "skip" and self._filter_subagents:
            return []
        try:
            return list(
                _map_event(
                    event,
                    self._session_id,
                    self._seen_tool_call_ids,
                    self._seen_model_event_ids,
                    self._seen_pending_event_ids,
                    self._seen_user_message_ids,
                )
            )
        except Exception:
            logger.warning(
                "ACP replay: mapping one event failed; skipping",
                exc_info=True,
            )
            return []


def replay_transcript(
    events: Sequence[Event],
    session_id: str,
    *,
    filter_subagents: bool = True,
) -> Iterator[SessionNotification]:
    """Map a sequence of past transcript events to session notifications.

    Batch generator wrapper around :class:`ReplayTranscriptor` for the
    replay-on-attach path. By default applies the same sub-agent depth
    filter the live router uses; pass ``filter_subagents=False`` to
    include events emitted inside sub-agent spans (useful for the raw
    firehose where the caller explicitly opted in).

    Sync generator — ``CancelledError`` propagates naturally
    (``BaseException`` is not caught by the per-event ``except Exception``
    inside :class:`ReplayTranscriptor`).
    """
    transcriptor = ReplayTranscriptor(session_id, filter_subagents=filter_subagents)
    for event in events:
        yield from transcriptor.process(event)


def _map_event(
    event: Event,
    session_id: str,
    seen_tool_call_ids: set[str],
    seen_model_event_ids: set[str],
    seen_pending_event_ids: set[str],
    seen_user_message_ids: set[str],
) -> Iterator[SessionNotification]:
    """Map a single event to zero-or-more session notifications.

    Shared by the live router (which threads its own dedup sets per
    session) and the replay helper (which uses one-shot local sets).
    """
    if isinstance(event, ModelEvent):
        yield from _map_model_event(
            event,
            session_id,
            seen_model_event_ids,
            seen_pending_event_ids,
            seen_user_message_ids,
        )
    elif isinstance(event, ToolEvent):
        yield from _map_tool_event(event, session_id, seen_tool_call_ids)


def _map_input_messages(
    event: ModelEvent,
    session_id: str,
    seen_user_message_ids: set[str],
) -> Iterator[SessionNotification]:
    """Emit system / user messages new since the previous turn.

    Walks ``event.input`` (the messages sent TO the model) backwards
    looking for the most recent assistant message; everything AFTER
    that point is "what arrived this turn." For the first model call
    there's no prior assistant, so we emit the whole input prefix
    (system prompt + initial user prompt). Per-id dedup means the
    same prompt sitting in every subsequent call's input only
    publishes once.

    Tool messages are skipped here — they ride on the corresponding
    ``ToolEvent`` notifications instead. Assistant messages are
    skipped too: they're the BOUNDARY we walk back to, not content
    we re-emit.

    Source attribution rides on ``_meta`` — see
    :func:`inspect_ext.input_message_chunk_meta` for the key set.
    """
    messages = event.input
    if not messages:
        return
    # Find the index of the most recent assistant — everything after
    # it is new this turn.
    cut = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], ChatMessageAssistant):
            cut = i
            break
    for msg in messages[cut + 1 :]:
        if not isinstance(msg, (ChatMessageUser, ChatMessageSystem)):
            continue
        msg_id = msg.id
        if msg_id is None or msg_id in seen_user_message_ids:
            continue
        text = _user_message_text(msg)
        if not text:
            continue
        seen_user_message_ids.add(msg_id)
        yield session_notification(
            session_id,
            UserMessageChunk(
                session_update="user_message_chunk",
                content=text_block(text),
                message_id=_model_event_message_id(msg_id),
                field_meta=input_message_chunk_meta(msg),
            ),
        )


def _user_message_text(msg: ChatMessageUser | ChatMessageSystem) -> str:
    """Extract display text from a user / system message.

    Multi-part content (text + images) currently renders text only —
    image-in-user-message is rare in Inspect today; full image support
    is a follow-on alongside the message widget's image content-block
    handling.
    """
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, ContentText) and block.text:
            parts.append(block.text)
    return "\n".join(parts)


def _map_model_event(
    event: ModelEvent,
    session_id: str,
    seen_model_event_ids: set[str],
    seen_pending_event_ids: set[str],
    seen_user_message_ids: set[str],
) -> Iterator[SessionNotification]:
    # Emit any system / user messages that landed since the previous
    # turn BEFORE the assistant chunks. Both pending and completed
    # phases run this; per-id dedup keeps the second a no-op. Doing
    # it on pending too means the user prompt appears immediately
    # when generation starts rather than waiting through the full
    # round-trip.
    yield from _map_input_messages(event, session_id, seen_user_message_ids)
    # Pending phase: emit a lightweight "generation started" signal so
    # the client can flip its status row to "generating" the moment the
    # model call begins, instead of waiting through the entire round
    # trip to publish anything. The signal is an empty AgentMessageChunk
    # carrying the message_id + inspect.model meta — enough for the
    # client to register an in-progress assistant message and start its
    # quiescence timer. No content is sent (the model hasn't returned),
    # so the displayed bubble is just the model chip until the completed
    # phase fills in the actual text. Deduped separately from completed
    # events so the same uuid can fire both phases.
    if event.pending:
        pending_uuid = event.uuid
        if pending_uuid is None or pending_uuid in seen_pending_event_ids:
            return
        seen_pending_event_ids.add(pending_uuid)
        pending_message_id = _model_event_message_id(pending_uuid)
        yield session_notification(
            session_id,
            AgentMessageChunk(
                session_update="agent_message_chunk",
                content=text_block(""),
                message_id=pending_message_id,
                field_meta=assistant_pending_chunk_meta(event, pending_uuid),
            ),
        )
        return
    uuid = event.uuid
    # "Did we tell the client a pending phase was open?" — drives
    # whether we owe a completion marker on the empty / no-content
    # exit paths. Without this, an error/cancel/empty-output
    # completion would leave the spinner stuck forever.
    pending_was_open = uuid is not None and uuid in seen_pending_event_ids
    # Drop empty completed events — no content to render. BUT if a
    # pending marker went out for this uuid, fire a completion marker
    # before returning so the client clears its spinner. Dedup via
    # ``seen_model_event_ids`` so repeated empty deliveries don't
    # double-emit.
    if event.output.empty:
        if pending_was_open and uuid is not None and uuid not in seen_model_event_ids:
            seen_model_event_ids.add(uuid)
            yield session_notification(
                session_id,
                AgentMessageChunk(
                    session_update="agent_message_chunk",
                    content=text_block(""),
                    message_id=_model_event_message_id(uuid),
                    field_meta=assistant_complete_chunk_meta(event, uuid),
                ),
            )
        return
    # De-dup by uuid: complete() calls _event_updated on the same
    # event after its initial _event, and cache hits emit a non-pending
    # event then call complete() on the same instance — both paths
    # would otherwise double-publish the same chunks.
    if uuid is not None:
        if uuid in seen_model_event_ids:
            return
        seen_model_event_ids.add(uuid)
    # message_id groups chunks from one model call into one logical
    # assistant message per ACP semantics ("change in messageId indicates
    # a new message has started"). The ACP schema mandates UUID format,
    # so we derive a stable UUIDv5 from the Inspect ModelEvent uuid
    # (which is a shortuuid, not RFC 4122 canonical form). The original
    # uuid is preserved in _meta via ``assistant_content_chunk_meta``.
    chunk_message_id = _model_event_message_id(uuid) if uuid is not None else None
    chunk_meta = assistant_content_chunk_meta(event, uuid)
    message = event.output.message
    emitted_content = False
    if not isinstance(message.content, list):
        if message.text:
            yield session_notification(
                session_id,
                AgentMessageChunk(
                    session_update="agent_message_chunk",
                    content=text_block(message.text),
                    message_id=chunk_message_id,
                    field_meta=chunk_meta,
                ),
            )
            emitted_content = True
    else:
        for block in message.content:
            if isinstance(block, ContentText) and block.text:
                yield session_notification(
                    session_id,
                    AgentMessageChunk(
                        session_update="agent_message_chunk",
                        content=text_block(block.text),
                        message_id=chunk_message_id,
                        field_meta=chunk_meta,
                    ),
                )
                emitted_content = True
            elif isinstance(block, ContentReasoning):
                # For redacted reasoning, `block.reasoning` may carry the
                # provider's encrypted/redacted payload — only `summary`
                # is display-safe. Mirror ContentReasoning.text's policy
                # (`self.reasoning if not self.redacted else (self.summary or "")`).
                reasoning_text = (
                    (block.summary or "") if block.redacted else block.reasoning
                )
                # Skip empty reasoning entirely — emitting an empty
                # chunk + flagging ``emitted_content=True`` would
                # suppress the completion marker AND leave the
                # client's pending spinner stuck (the TUI only
                # clears pending on non-empty content or an explicit
                # completion marker). Empty reasoning happens for
                # redacted blocks with no summary and for some
                # providers' zero-thinking-token responses.
                if reasoning_text:
                    yield session_notification(
                        session_id,
                        AgentThoughtChunk(
                            session_update="agent_thought_chunk",
                            content=text_block(reasoning_text),
                            message_id=chunk_message_id,
                            field_meta=chunk_meta,
                        ),
                    )
                    emitted_content = True
    # Generation-complete marker for tool-only responses + the
    # no-content / empty-reasoning paths. The pending phase emits an
    # empty chunk so the client can flip its status row to
    # "generating" immediately; without something matching it on the
    # complete phase, the client's spinner stays stuck. When real
    # content WAS emitted the client clears its pending marker off
    # the first non-empty chunk, so we skip the marker there to keep
    # the wire quiet. Gated on ``pending_was_open`` so cache-hit
    # paths (no pending → no spinner to clear) don't manufacture an
    # empty assistant bubble.
    if not emitted_content and pending_was_open and uuid is not None:
        yield session_notification(
            session_id,
            AgentMessageChunk(
                session_update="agent_message_chunk",
                content=text_block(""),
                message_id=chunk_message_id,
                field_meta=assistant_complete_chunk_meta(event, uuid),
            ),
        )
    # Emit UsageUpdate for every non-empty model event with known usage
    # and a known context window. ACP semantics: "Tokens currently in
    # context" / "Total context window size". We do NOT gate this on
    # whether chunks were emitted — a common pattern is content="" plus
    # tool_calls (no chunks for the TUI to render, but real tokens
    # consumed). Schema requires both used + size; if either is unknown
    # we skip rather than send a misleading size=0.
    usage_update = _build_usage_update(event)
    if usage_update is not None:
        # SessionNotification directly: the acp.helpers.session_notification
        # helper's type annotation predates UsageUpdate joining the
        # SessionUpdate union (the schema discriminated union includes it,
        # but the helper's typedef is narrower). Constructing the
        # notification by hand sidesteps the type mismatch.
        #
        # Piggyback the sample's running ``total_messages`` on the outer
        # ``field_meta`` so the TUI's header re-renders the ``messages``
        # chip on the same per-model-event tick that drives ``tokens``.
        yield SessionNotification(
            session_id=session_id,
            update=usage_update,
            field_meta={
                TOTAL_MESSAGES_META_KEY: _active_sample_total_messages(session_id)
            },
        )


# UUIDv5 namespace for deriving message_id from Inspect ModelEvent uuids.
# Generated once and frozen; do not regenerate (would invalidate ids
# across version boundaries for any client that pinned an id).
_INSPECT_MESSAGE_ID_NAMESPACE = _uuid_module.UUID(
    "0e22b6ad-7e30-5d7b-9a87-78e3f56f4f93"
)


def _model_event_message_id(model_event_uuid: str) -> str:
    """Map an Inspect ModelEvent shortuuid to an ACP-compliant UUIDv5 string.

    ACP's message_id field mandates UUID format; Inspect events use
    shortuuid which isn't parseable as canonical UUID. UUIDv5 over a
    fixed namespace gives a stable, deterministic mapping (same input
    → same id) so chunks from one event still group correctly on the
    client.
    """
    return str(_uuid_module.uuid5(_INSPECT_MESSAGE_ID_NAMESPACE, model_event_uuid))


def _active_sample_total_messages(session_id: str) -> int:
    """Look up ``ActiveSample.total_messages`` for the given ACP session.

    Returns 0 if no matching active sample is found (e.g. the sample
    finished between the model event firing and our lookup) — the TUI
    treats 0 as "no data" and renders an em-dash, matching the
    ``totalTokens=0`` fallback the picker already uses.
    """
    from inspect_ai.log._samples import active_samples

    for sample in active_samples():
        sess = sample.acp_transport
        if sess is not None and sess.session_id == session_id:
            return sample.total_messages
    return 0


def _build_usage_update(event: ModelEvent) -> UsageUpdate | None:
    """Build a UsageUpdate for ``event`` if usage and context window are known.

    ACP's UsageUpdate requires both ``used`` and ``size``; if the model
    didn't report usage (e.g. mock providers) or we can't resolve a
    context window for the model, we return None and the caller skips
    the emission (client just won't render the chip for this turn).
    """
    usage = event.output.usage
    if usage is None:
        return None
    info = get_model_info(event.model)
    if info is None or info.context_length is None:
        return None
    # input_tokens reports tokens that were in context on this call.
    # cached read/write should be included for the true total since
    # they're physically present in the request. output_tokens is
    # included so the chip reflects "size of state after the call",
    # which matches what an operator looking at a running agent expects.
    used = usage.input_tokens + usage.output_tokens
    if usage.input_tokens_cache_read is not None:
        used += usage.input_tokens_cache_read
    if usage.input_tokens_cache_write is not None:
        used += usage.input_tokens_cache_write
    return UsageUpdate(
        session_update="usage_update",
        used=max(used, 0),
        size=info.context_length,
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
            update_tool_call(
                tool_call_id=event.id,
                status=status,
                content=_content_for_update(event),
            ),
        )
    else:
        seen_tool_call_ids.add(event.id)
        # Title: descriptive per-tool summary derived from the args
        # (``bash: ls -la``, ``Read foo.py``, etc.). Editor cards
        # collapse to a single title line in the transcript view,
        # so a bare ``"bash"`` makes a list of bash calls
        # indistinguishable. raw_input is always sent so clients
        # have the canonical args for the debug "raw" view. content
        # carries the markdown view (the viewer's rendered code
        # block) for clients that surface inline content. kind helps
        # icon selection but we deliberately never set ``"execute"``
        # for shell tools — see ``_TOOL_KIND_BY_NAME`` in
        # ``_tool_content``.
        yield session_notification(
            session_id,
            start_tool_call(
                tool_call_id=event.id,
                title=_descriptive_title(event),
                status=status,
                kind=_tool_kind_for(event.function),
                raw_input=event.arguments,
                content=_content_for_start(event),
            ),
        )


def _tool_call_status(event: ToolEvent) -> _ToolCallStatus:
    if event.pending:
        return "in_progress"
    if event.error is not None or event.failed:
        return "failed"
    return "completed"
