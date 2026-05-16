"""Pure-Python state object that consumes ACP ``session/update`` notifications.

Drives the Phase 2 TUI rendering surface (status row, transcript, tool
cards). Deliberately Textual-agnostic — the SessionScreen subscribes to
state changes via a plain callback and re-renders; tests can exercise the
whole consume/derive pipeline without an event loop or pilot.

What it tracks:

- Ordered transcript items — message groups (assistant text + reasoning
  + user) grouped by ``ContentChunk.message_id`` per ACP protocol; tool
  calls (start + progress merged) keyed by ``tool_call_id``. ``items``
  is the display order; ``_*_by_id`` indexes drive fast lookups.
- Most-recent model name from ``AgentMessageChunk._meta["inspect.model"]``
  (Phase 2 A3) — drives the "model X" chip in the status row.
- Latest ``UsageUpdate`` (used / size) — drives the "tokens N / M" chip.
- Status pill state, derived from the above + a 2-second quiescence
  heuristic for the transient ``Generating`` window.

Out of scope for Phase 2 (and absent here):

- Terminal pill states (``Scoring`` / ``Completed`` / ``Errored`` /
  ``Interrupted``) — need server-side notifications that don't exist
  natively in ACP and aren't extensions yet (Phase 5).
- Plan / mode / config updates — the design defers all of these.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal, Union

from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    SessionInfoUpdate,
    SessionNotification,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)

# The Generating pill stays visible for this many seconds after the most
# recent chunk before falling back to Awaiting input. Picked to feel
# responsive (UI doesn't linger in a stale "thinking" state) without
# flickering during typical stream gaps.
_GENERATING_QUIESCENCE_SECONDS = 2.0


MessageRole = Literal["user", "assistant"]

SegmentKind = Literal["text", "reasoning"]


@dataclass
class Segment:
    """A homogeneous run of content within a MessageGroup.

    Successive chunks of the same kind extend the last segment; a kind
    change starts a new one. This preserves the actual arrival order
    (text → reasoning → text round-trips correctly) so the renderer
    can show interleaved thought / response without losing structure.
    """

    kind: SegmentKind
    text: str


@dataclass
class MessageGroup:
    """One logical message — the unit a client renders as a single bubble.

    All chunks sharing a ``message_id`` accumulate here per ACP intent
    ("all chunks belonging to the same message share the same
    messageId"). The router emits BOTH ``AgentMessageChunk`` (text)
    AND ``AgentThoughtChunk`` (reasoning) from one model call with the
    same id — they're two flavors of content from one assistant turn
    and render together. ``segments`` captures the ordered mix; the
    group's ``role`` is the top-level kind (``user`` or ``assistant``).
    Reasoning is always carried as a segment within an ``assistant``
    group, never as a top-level role.
    """

    message_id: str
    role: MessageRole
    segments: list[Segment] = field(default_factory=list)
    model: str | None = None
    """Source model name from ``_meta['inspect.model']`` if present."""

    received_at: float = field(default_factory=time.monotonic)

    @property
    def text(self) -> str:
        """Concatenated TEXT segments (excludes reasoning).

        Convenience for callers that want only the displayed body —
        reasoning is rendered separately (dimmed sub-block). Iterate
        ``segments`` directly to render with full structure.
        """
        return "".join(s.text for s in self.segments if s.kind == "text")

    @property
    def reasoning_text(self) -> str:
        """Concatenated REASONING segments.

        For callers that want the full thought trace independently of
        the text response.
        """
        return "".join(s.text for s in self.segments if s.kind == "reasoning")


ToolCallStatus = Literal["pending", "in_progress", "completed", "failed"]


@dataclass
class ToolCallState:
    """Merged view of a tool call across its ToolCallStart + ToolCallProgress.

    ``start_time`` is captured at first sight (the ToolCallStart receive
    instant) and ``end_time`` is set when ``status`` reaches a terminal
    value. The widget reads these for client-side duration derivation
    (no native duration field in ACP — see plan's deferred-extension
    discussion).
    """

    tool_call_id: str
    title: str | None = None
    kind: str | None = None
    status: ToolCallStatus = "in_progress"
    content: list[Any] | None = None
    raw_input: Any = None
    raw_output: Any = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")

    @property
    def duration_seconds(self) -> float | None:
        """None until the tool reaches a terminal status."""
        if self.end_time is None:
            return None
        return self.end_time - self.start_time


TranscriptItem = Union[MessageGroup, ToolCallState]


class StatusState(str, Enum):
    """The Phase-2 subset of the status pill state machine."""

    AWAITING_INPUT = "awaiting_input"
    GENERATING = "generating"
    CALLING_TOOLS = "calling_tools"


@dataclass
class UsageState:
    """Snapshot of the latest UsageUpdate."""

    used: int
    size: int


class SessionState:
    """Holds the rendered state of one attached ACP session.

    Designed to be driven entirely by ``consume(notification)`` calls
    from the client's notification handler. Subscribers (typically a
    Textual screen) register a sync callback via :meth:`subscribe` and
    are notified after every state mutation.

    All time-sensitive derivations (status quiescence, duration) read
    ``_now()`` so tests can inject a deterministic clock.
    """

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self.items: list[TranscriptItem] = []
        self._messages_by_id: dict[str, MessageGroup] = {}
        self._tool_calls_by_id: dict[str, ToolCallState] = {}
        self.current_model: str | None = None
        self.usage: UsageState | None = None
        self.session_title: str | None = None
        self._last_chunk_at: float | None = None
        self._subscribers: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Subscribers
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a sync state-change callback. Returns an unsubscribe."""
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def _notify(self) -> None:
        # Snapshot first — a subscriber callback may mutate the list.
        for cb in list(self._subscribers):
            try:
                cb()
            except Exception:  # noqa: BLE001 — never let a subscriber kill the loop
                pass

    # ------------------------------------------------------------------
    # Consume notifications
    # ------------------------------------------------------------------

    def consume(self, notification: SessionNotification) -> None:
        """Apply one notification to state + notify subscribers.

        Unknown variants are silently ignored — the server may add new
        SessionUpdate kinds (Plan, Mode, Config) that Phase 2 doesn't
        render. Dropping them keeps the client forward-compatible.
        """
        update = notification.update
        changed = False
        if isinstance(update, (UserMessageChunk, AgentMessageChunk, AgentThoughtChunk)):
            changed = self._consume_chunk(update)
        elif isinstance(update, ToolCallStart):
            changed = self._consume_tool_start(update)
        elif isinstance(update, ToolCallProgress):
            changed = self._consume_tool_progress(update)
        elif isinstance(update, UsageUpdate):
            changed = self._consume_usage(update)
        elif isinstance(update, SessionInfoUpdate):
            changed = self._consume_session_info(update)
        if changed:
            self._notify()

    def _role_for(
        self,
        update: UserMessageChunk | AgentMessageChunk | AgentThoughtChunk,
    ) -> MessageRole:
        if isinstance(update, UserMessageChunk):
            return "user"
        # AgentMessageChunk AND AgentThoughtChunk both belong to one
        # assistant turn; reasoning is a segment KIND, not a top-level
        # role (see MessageGroup docstring).
        return "assistant"

    def _segment_kind_for(
        self,
        update: UserMessageChunk | AgentMessageChunk | AgentThoughtChunk,
    ) -> SegmentKind:
        return "reasoning" if isinstance(update, AgentThoughtChunk) else "text"

    def _consume_chunk(
        self,
        update: UserMessageChunk | AgentMessageChunk | AgentThoughtChunk,
    ) -> bool:
        # message_id missing: Phase 2 server should always set it (router
        # uses ModelEvent.uuid → UUIDv5 via A1). If absent, treat each
        # chunk as its own message so we don't blindly concatenate
        # unrelated content into one bubble.
        message_id = update.message_id
        if message_id is None:
            message_id = f"__nogroup__:{len(self.items)}"

        group = self._messages_by_id.get(message_id)
        if group is None:
            group = MessageGroup(
                message_id=message_id,
                role=self._role_for(update),
                received_at=self._now(),
            )
            self._messages_by_id[message_id] = group
            self.items.append(group)

        # Append to the segment list. Adjacent chunks of the same kind
        # extend the last segment so multi-chunk text streams as one
        # block; a kind change (text → reasoning or vice versa) starts
        # a new segment so the renderer can show interleaved
        # thought / response in true arrival order.
        text = self._text_from_content(update.content)
        if text:
            kind = self._segment_kind_for(update)
            if group.segments and group.segments[-1].kind == kind:
                group.segments[-1].text += text
            else:
                group.segments.append(Segment(kind=kind, text=text))

        # Track model from meta. For assistant/reasoning chunks the
        # router stamps the originating ModelEvent.model in
        # _meta["inspect.model"]; user chunks have no model attribution.
        meta = getattr(update, "field_meta", None) or {}
        model = meta.get("inspect.model")
        if isinstance(model, str) and model:
            group.model = model
            self.current_model = model

        # The "Generating" derivation is time-based — record the latest
        # chunk activity so :attr:`status` can decide when to fall back
        # to AWAITING_INPUT. **NOTE for integration layer**: the
        # GENERATING → AWAITING_INPUT transition is time-driven only;
        # SessionState does NOT fire a notification when the quiescence
        # window expires. The SessionScreen needs its own ~500ms timer
        # to call `refresh()` so the pill flips after the last chunk.
        self._last_chunk_at = self._now()
        return True

    def _text_from_content(self, content: Any) -> str:
        """Extract display text from an ACP ContentBlock.

        Pure TextContentBlock returns its text. Other block types
        (image / audio / resource / embedded resource) render as a
        short placeholder so the transcript shows the event happened.
        Phase 2 doesn't render those richly; later phases can.
        """
        if isinstance(content, TextContentBlock):
            return content.text
        type_name = getattr(content, "type", None)
        if type_name == "image":
            return "[image]"
        if type_name == "audio":
            return "[audio]"
        if type_name in ("resource_link", "resource"):
            return "[resource]"
        return ""

    def _consume_tool_start(self, update: ToolCallStart) -> bool:
        tc = self._tool_calls_by_id.get(update.tool_call_id)
        status = update.status or "in_progress"
        if tc is None:
            tc = ToolCallState(
                tool_call_id=update.tool_call_id,
                title=update.title,
                kind=update.kind,
                status=status,
                content=list(update.content) if update.content is not None else None,
                raw_input=update.raw_input,
                raw_output=update.raw_output,
                start_time=self._now(),
            )
            if tc.status in ("completed", "failed"):
                tc.end_time = tc.start_time
            self._tool_calls_by_id[update.tool_call_id] = tc
            self.items.append(tc)
            return True
        # Defensive: a duplicate start (e.g. replayed). Merge non-None
        # fields without re-appending to items.
        self._merge_tool_fields(tc, update)
        return True

    def _consume_tool_progress(self, update: ToolCallProgress) -> bool:
        tc = self._tool_calls_by_id.get(update.tool_call_id)
        if tc is None:
            # Out-of-order: progress before start. Synthesize a state so
            # the operator at least sees a card. Real "progress without
            # start" shouldn't happen on the wire today; this is
            # defensive against future server / replay edge cases.
            tc = ToolCallState(
                tool_call_id=update.tool_call_id,
                title=update.title,
                kind=update.kind,
                status=update.status or "in_progress",
                content=list(update.content) if update.content is not None else None,
                raw_input=update.raw_input,
                raw_output=update.raw_output,
                start_time=self._now(),
            )
            self._tool_calls_by_id[update.tool_call_id] = tc
            self.items.append(tc)
            if tc.status in ("completed", "failed"):
                tc.end_time = tc.start_time
            return True
        self._merge_tool_fields(tc, update)
        return True

    def _merge_tool_fields(
        self,
        tc: ToolCallState,
        update: ToolCallStart | ToolCallProgress,
    ) -> None:
        """ACP semantics: any non-None field on the update replaces in-state."""
        if update.status is not None:
            tc.status = update.status
            if tc.status in ("completed", "failed") and tc.end_time is None:
                tc.end_time = self._now()
        if update.title is not None:
            tc.title = update.title
        if update.kind is not None:
            tc.kind = update.kind
        if update.content is not None:
            # ToolCallProgress.content REPLACES the start's content per
            # ACP semantics — the server explicitly prepends the input
            # view when sending result blocks so nothing is lost on the
            # wire. Client mirrors that: full replacement, no merge.
            tc.content = list(update.content)
        if update.raw_input is not None:
            tc.raw_input = update.raw_input
        if update.raw_output is not None:
            tc.raw_output = update.raw_output

    def _consume_usage(self, update: UsageUpdate) -> bool:
        self.usage = UsageState(used=update.used, size=update.size)
        return True

    def _consume_session_info(self, update: SessionInfoUpdate) -> bool:
        # Distinguish "title field was explicitly set" from "title field
        # was omitted". An update that carries only updated_at (or other
        # future fields) would otherwise wipe the stored title because
        # Pydantic gives `update.title == None` in both cases. Use
        # model_fields_set to check explicit presence.
        if "title" not in update.model_fields_set:
            return False
        # Now `update.title` is meaningful: a real value sets it; an
        # explicit None is the ACP-defined *destructive clear*.
        self.session_title = update.title
        return True

    # ------------------------------------------------------------------
    # Derivations
    # ------------------------------------------------------------------

    @property
    def tools_in_flight(self) -> int:
        return sum(
            1
            for tc in self._tool_calls_by_id.values()
            if tc.status == "in_progress" or tc.status == "pending"
        )

    @property
    def status(self) -> StatusState:
        """Current pill state derived from in-flight signal + quiescence.

        Order matters:
        - Any tool in flight → CALLING_TOOLS (clear signal, always wins)
        - Recent chunk activity → GENERATING (within quiescence window)
        - Otherwise → AWAITING_INPUT (resting)
        """
        if self.tools_in_flight > 0:
            return StatusState.CALLING_TOOLS
        if self._last_chunk_at is not None:
            if (self._now() - self._last_chunk_at) < _GENERATING_QUIESCENCE_SECONDS:
                return StatusState.GENERATING
        return StatusState.AWAITING_INPUT
