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

from inspect_ai.agent._acp.inspect_ext import (
    MESSAGE_ROLE_META_KEY,
    MODEL_EVENT_COMPLETE_META_KEY,
    MODEL_EVENT_PENDING_META_KEY,
    MODEL_META_KEY,
    PICKER_META_KEY,
    USER_SOURCE_META_KEY,
)

# The Generating pill stays visible for this many seconds after the most
# recent chunk before falling back to Awaiting input. Picked to feel
# responsive (UI doesn't linger in a stale "thinking" state) without
# flickering during typical stream gaps.
_GENERATING_QUIESCENCE_SECONDS = 2.0

# Lifecycle ``running`` pill stays visible for this many seconds after
# ``has_active_work`` drops to False. Covers the sub-second gaps
# between model events and tool calls (otherwise the pill flickers
# "running → idle → running" several times per turn). Real activity
# either resumes inside this window (re-stamping the timestamp) or
# never resumes (which is the genuine idle case worth surfacing).
_RUNNING_QUIESCENCE_SECONDS = 2.0

_MAX_ASSISTANT_TURNS = 15
"""Maximum number of assistant message groups retained in the transcript.

State-side cap (not just a render limit): older items are evicted from
``self.items`` and the lookup indexes so notifications, transcript
refreshes, and per-tool widget diffing all scale with the *window*
size rather than the full history. The user can still re-attach to
see the full transcript via the server's replay path; this limit only
governs what the running TUI holds in memory.

15 matches roughly the longest reasoning window an operator can
visually scan in one screen at typical chunk sizes — past that, the
oldest exchange is more "history" than "context."
"""


MessageRole = Literal["user", "assistant", "system"]

SegmentKind = Literal["text", "reasoning"]


def _group_has_content(group: "MessageGroup") -> bool:
    """True iff the group has at least one segment with non-empty text.

    The router emits an empty ``AgentMessageChunk`` as a "generation
    started" marker — that bubble has zero useful content until real
    text arrives. ``mark_interrupted`` uses this predicate to decide
    whether to drop the group (no content yet) or keep it (partial
    output streamed before the cancel landed).
    """
    return any(segment.text for segment in group.segments)


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

    pending: bool = False
    """Whether the originating model event is still in flight.

    True while the server has sent a pending marker but no completion
    signal yet. Flipped to False on either a real content chunk
    (generation has produced output) or an explicit completion marker
    (tool-only response). Lets the renderer distinguish "still
    generating" from "done, no content" — only the former animates.
    """

    retries: int = 0
    """Number of retry attempts collapsed into this group.

    When a model event errors and Inspect retries, each attempt fires
    a fresh pending → completion cycle with a NEW uuid (and therefore
    a new message_id). Rather than render N empty stacked bubbles,
    the client collapses consecutive empty assistant-pending signals
    for the same model into ONE group, incrementing this counter.
    Zero means the first (and so far only) attempt.
    """

    pending_started_at: float | None = None
    """``time.monotonic()`` at the first pending signal for this group.

    Used to render an elapsed timer on the chip while ``pending`` is
    True. Survives retries (set once at first pending, not reset on
    each retry attempt) so the user sees total wall time across all
    attempts, not just the latest attempt.
    """

    user_source: str | None = None
    """``ChatMessageUser.source`` for user groups, ``None`` for assistant.

    Carried from the server via ``_meta['inspect.user_source']`` —
    typical values are ``input`` (the dataset input that kicked the
    sample off), ``operator`` (an operator-submitted message from
    the TUI composer), ``generate`` (synthesized inside a sub-agent
    flow), or ``None``. Drives the chip suffix (``user · operator``
    vs. ``user · input`` etc.) so the operator can tell whose prompt
    triggered the next assistant turn.
    """

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
        # message_ids for which the server has signalled a pending
        # model event but not yet the matching completion marker. While
        # this set is non-empty the status row stays "generating" so
        # the row reflects in-flight generation across the model's
        # full think+respond latency (often well beyond the inter-chunk
        # quiescence window). See _consume_chunk for the lifecycle.
        self._pending_message_ids: set[str] = set()
        # Retry collapsing: maps a retry's message_id to the original
        # group's message_id so subsequent chunks (completion marker,
        # any content if it eventually arrives) flow into the existing
        # group instead of creating a new bubble. Populated when a
        # pending signal lands and the most recent transcript item is
        # an empty assistant group for the same model.
        self._message_id_aliases: dict[str, str] = {}
        # message_ids the operator explicitly cancelled via Esc that
        # had no content yet. The server still emits a completion
        # marker for these (an empty AgentMessageChunk with the
        # ``inspect.model_event_complete`` meta) once the ModelEvent's
        # pending flag clears, which would otherwise re-create the
        # bubble we just dropped — as a non-pending, no-content
        # ghost. Late chunks for these ids are silently dropped in
        # ``_consume_chunk``. Bounded by the count of operator
        # interrupts that fired before any content streamed; in
        # practice tiny.
        self._dropped_message_ids: set[str] = set()
        # Sticky flag flipped True by ``mark_interrupted`` and cleared
        # the next time real content lands. Powers the resting-state
        # lifecycle indicator's ``interrupted`` value — without it
        # there's no way to distinguish "Esc was hit and the turn
        # unwound" from "the turn completed normally", since both
        # leave ``has_active_work`` False.
        self._interrupted: bool = False
        # Sticky flag flipped True by ``mark_complete`` when the
        # server-side session ends (transport disconnect / explicit
        # end). Once set the lifecycle pill stays on ``complete``
        # regardless of in-flight residue — the session is gone and
        # the UI is just a read-only postmortem from that point on.
        self._complete: bool = False
        # Wall-clock of the most recent moment ``has_active_work`` was
        # True. Used to keep the lifecycle pill on ``running`` through
        # the sub-second micro-gaps between model events and tool
        # calls (otherwise the pill strobes "running → idle → running"
        # several times per turn as each pending/tool finishes
        # nanoseconds before the next one starts). Same quiescence
        # idea the ``status`` property uses for ``GENERATING``, but
        # this one tracks ALL active work — chunks + tool events —
        # instead of just chunks.
        self._last_running_at: float | None = None
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
    # Operator-driven mutations
    # ------------------------------------------------------------------

    @property
    def lifecycle(self) -> Literal["idle", "running", "interrupted", "complete"]:
        """Coarse-grained turn lifecycle for the header pill.

        Four states, in priority order so a true terminal signal
        always wins over transient turn state:

        - ``complete``: the server-side session has ended (transport
          disconnect / explicit end). Sticky — once set, stays set.
        - ``running``: at least one model event or tool call is
          currently in flight (``has_active_work``), OR the last
          activity was within ``_RUNNING_QUIESCENCE_SECONDS`` (covers
          the sub-second gap between, e.g., a model event completing
          and the next tool call starting — without the tail the
          pill strobed on every micro-gap).
        - ``interrupted``: the operator hit Esc during a turn and
          no fresh content has arrived since. Checked *before* the
          quiescence tail so an Esc immediately reads as interrupted
          rather than waiting out the tail in ``running``.
        - ``idle``: resting between turns or the initial state. Pill
          hides on this value so the chrome stays quiet when nothing
          is happening — the indicator exists to signal change, not
          to fill space at rest.
        """
        if self._complete:
            return "complete"
        if self.has_active_work:
            return "running"
        if self._interrupted:
            return "interrupted"
        if (
            self._last_running_at is not None
            and (self._now() - self._last_running_at) < _RUNNING_QUIESCENCE_SECONDS
        ):
            return "running"
        return "idle"

    def mark_complete(self) -> None:
        """Sticky-mark the session as ended (transport disconnect / end).

        Idempotent — subsequent calls are no-ops. Notifies subscribers
        on the first transition so the pill can flip immediately.
        """
        if self._complete:
            return
        self._complete = True
        self._notify()

    def mark_interrupted(self) -> None:
        """Optimistically clear in-flight signals after the operator hits Esc.

        The cancel notification round-trips through the server (agent
        loop unwind → transcript update → router emit → wire back), so
        the spinner / status pill would otherwise stay on
        ``GENERATING`` or ``CALLING_TOOLS`` for the full propagation
        window. Clearing locally gives instant feedback; if the model
        actually produces content before the cancel lands, the next
        chunk just re-establishes pending state honestly.

        Four things change:
        - pending message groups with no content yet are *dropped*
          entirely (the empty "assistant is thinking" bubble is just
          chrome once we know the turn was cancelled before any text
          arrived); pending groups that did stream content keep their
          text but lose ``pending=True``.
        - ``_pending_message_ids`` is cleared (drops
          :attr:`StatusState.GENERATING`).
        - in-flight tool calls are marked ``failed`` with ``end_time``
          stamped so the card stops spinning.
        - the inter-chunk quiescence timer is reset so the
          quiescence-based ``GENERATING`` branch doesn't keep firing
          until the timer expires on its own.
        """
        changed = False
        empty_pending_ids: list[str] = []
        for message_id in list(self._pending_message_ids):
            group = self._messages_by_id.get(message_id)
            if group is None:
                continue
            if _group_has_content(group):
                if group.pending:
                    group.pending = False
                    changed = True
            else:
                empty_pending_ids.append(message_id)
        if empty_pending_ids:
            tombstone_ids = self._drop_message_groups(empty_pending_ids)
            # Tombstone the canonical ids AND any retry-collapse alias
            # keys that pointed at them — the server's late completion
            # marker could legitimately arrive under either. See
            # ``_dropped_message_ids`` field comment.
            self._dropped_message_ids.update(tombstone_ids)
            changed = True
        if self._pending_message_ids:
            self._pending_message_ids.clear()
            changed = True
        if self._last_chunk_at is not None:
            self._last_chunk_at = None
            changed = True
        # Reset the running-quiescence stamp too: without this, after
        # ``_interrupted`` clears (on the next real chunk), a stale
        # stamp from before the Esc would briefly extend the
        # ``running`` tail past a genuinely-idle gap.
        if self._last_running_at is not None:
            self._last_running_at = None
            changed = True
        now = self._now()
        for tc in self._tool_calls_by_id.values():
            if tc.status in ("pending", "in_progress"):
                tc.status = "failed"
                if tc.end_time is None:
                    tc.end_time = now
                changed = True
        # ``_interrupted`` flips to True regardless of ``changed`` so
        # the lifecycle indicator reflects the Esc even if no in-flight
        # work was actually torn down (operator pressed Esc twice, or
        # a quiescence-tail Esc that was previously gated out).
        if not self._interrupted:
            self._interrupted = True
            changed = True
        if changed:
            self._notify()

    def _drop_message_groups(self, message_ids: list[str]) -> set[str]:
        """Remove the named groups from ``items`` and the lookup indexes.

        Mirrors the cleanup the turn-cap path runs — pops the message
        index, drops any retry-collapse aliases pointing at the
        dropped ids, and removes the items themselves. Caller is
        responsible for the ``_pending_message_ids`` cleanup since
        not every caller wants the same scope there.

        Returns the union of the dropped canonical ids and any alias
        KEYS that pointed at them. Both are message_ids a late chunk
        could legitimately arrive under: server-side a content chunk
        always uses the canonical id, but the empty completion
        marker may travel under the original retry id depending on
        which event uuid the router resolved. Callers wanting full
        suppression (e.g. :meth:`mark_interrupted`) tombstone the
        whole returned set so neither id can resurrect the bubble.
        """
        drop = set(message_ids)
        self.items = [
            item
            for item in self.items
            if not (isinstance(item, MessageGroup) and item.message_id in drop)
        ]
        for mid in drop:
            self._messages_by_id.pop(mid, None)
        pruned_alias_keys: set[str] = set()
        if self._message_id_aliases:
            kept: dict[str, str] = {}
            for k, v in self._message_id_aliases.items():
                if v in drop:
                    pruned_alias_keys.add(k)
                else:
                    kept[k] = v
            self._message_id_aliases = kept
        return drop | pruned_alias_keys

    # ------------------------------------------------------------------
    # Consume notifications
    # ------------------------------------------------------------------

    def consume(self, notification: SessionNotification) -> None:
        """Apply one notification to state + notify subscribers.

        Unknown variants are silently ignored — the server may add new
        SessionUpdate kinds (Plan, Mode, Config) that Phase 2 doesn't
        render. Dropping them keeps the client forward-compatible.
        """
        # Bind / picker confirmation notifications carry the picker meta
        # key on the OUTER SessionNotification (set by
        # ``build_picker_notification``); the inner chunk just has the
        # text restating the bind ("Bound to <task> / sample <s>"). Our
        # meta row already shows that info, so drop these locally
        # without touching state.
        outer_meta = getattr(notification, "field_meta", None) or {}
        if PICKER_META_KEY in outer_meta:
            return

        update = notification.update
        # Snapshot BEFORE applying the update so the running-tail
        # stamp also fires on the update that ENDS active work —
        # otherwise a long pending (>2s) that completes on a single
        # content/completion chunk would leave a stale stamp and the
        # lifecycle would skip the tail and fall straight to ``idle``.
        was_active = self.has_active_work
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
            # Stamp the running-window timestamp BEFORE notifying so
            # subscribers (notably the header pill) see the freshest
            # ``has_active_work`` and the quiescence window in sync.
            # Stamp on EITHER edge of has_active_work being True
            # (before-or-after the update): covers steady-state
            # activity AND the True→False transition (when the
            # current update is what ended the only active work, so
            # the tail starts fresh at that moment).
            if was_active or self.has_active_work:
                self._last_running_at = self._now()
            self._notify()

    def _role_for(
        self,
        update: UserMessageChunk | AgentMessageChunk | AgentThoughtChunk,
    ) -> MessageRole:
        if isinstance(update, UserMessageChunk):
            # The router uses UserMessageChunk for SYSTEM messages too
            # (ACP has no system-message variant), distinguishing them
            # via ``_meta['inspect.message_role'] = 'system'``. Honor
            # that here so the chip can render the system label
            # without the rest of the consume path needing to care.
            meta = getattr(update, "field_meta", None) or {}
            if meta.get(MESSAGE_ROLE_META_KEY) == "system":
                return "system"
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
        message_id = update.message_id or f"__nogroup__:{len(self.items)}"
        # Resolve through any retry-collapse alias set by a prior call —
        # subsequent chunks for an aliased id (the completion marker,
        # any late content) target the original group.
        message_id = self._message_id_aliases.get(message_id, message_id)

        # Late chunks for groups the operator explicitly cancelled
        # (via ``mark_interrupted``) are silently dropped — otherwise
        # the server's empty completion marker would re-create the
        # bubble as a non-pending, content-empty ghost. See the
        # ``_dropped_message_ids`` field comment for the lifecycle.
        if message_id in self._dropped_message_ids:
            return False

        meta = getattr(update, "field_meta", None) or {}
        role = self._role_for(update)
        is_pending_signal = bool(meta.get(MODEL_EVENT_PENDING_META_KEY))

        group = self._resolve_or_create_group(
            message_id, role, meta, is_pending_signal, update.message_id
        )
        self._apply_pending_lifecycle(group, is_pending_signal, meta)
        self._append_segment(group, update)
        self._apply_chunk_metadata(group, role, meta)
        # Fresh non-tombstoned content clears the "interrupted" residue
        # — the next turn's chunks have started flowing, so the
        # lifecycle indicator should leave the interrupted state. Done
        # after the resolve/apply calls above so we only react to
        # chunks that actually made it through (not the early-return
        # dropped paths above).
        self._interrupted = False

        # The "Generating" derivation is time-based — record the latest
        # chunk activity so :attr:`status` can decide when to fall back
        # to AWAITING_INPUT. **NOTE for integration layer**: the
        # GENERATING → AWAITING_INPUT transition is time-driven only;
        # SessionState does NOT fire a notification when the quiescence
        # window expires. The SessionScreen needs its own ~500ms timer
        # to call `refresh()` so the pill flips after the last chunk.
        self._last_chunk_at = self._now()
        return True

    def _resolve_or_create_group(
        self,
        message_id: str,
        role: MessageRole,
        meta: dict[str, Any],
        is_pending_signal: bool,
        original_message_id: str | None,
    ) -> MessageGroup:
        """Look up or create the MessageGroup for this chunk.

        Three paths:
        - existing group by id → return it.
        - retry-collapse hit (see :meth:`_should_retry_collapse`) →
          reuse the prior empty assistant bubble, bump ``retries``,
          alias the new id, drop the stale pending tracking.
        - otherwise → create a fresh group, register it, enforce the
          assistant-turn window cap.
        """
        existing = self._messages_by_id.get(message_id)
        if existing is not None:
            return existing
        if self._should_retry_collapse(role, meta, is_pending_signal):
            # Predicate guarantees self.items[-1] is an empty assistant
            # MessageGroup — narrow once for mypy.
            prior = self.items[-1]
            assert isinstance(prior, MessageGroup)
            prior.retries += 1
            # Aliasing: any further chunks bearing the retry's
            # message_id (completion marker, late content) need to
            # find this group too.
            self._message_id_aliases[original_message_id or message_id] = (
                prior.message_id
            )
            # Drop the previous attempt's tracking entry so the
            # status row's pending set doesn't accumulate stale ids.
            self._pending_message_ids.discard(prior.message_id)
            return prior
        group = MessageGroup(message_id=message_id, role=role)
        self._messages_by_id[message_id] = group
        self.items.append(group)
        # State-side window cap: only the *new assistant group* path
        # can push us over the limit (tool calls slot between existing
        # assistants, user messages don't count). Trim here so the
        # rest of this method works against the pruned window if we
        # just shrank it.
        if role == "assistant":
            self._enforce_turn_cap()
        return group

    def _should_retry_collapse(
        self,
        role: MessageRole,
        meta: dict[str, Any],
        is_pending_signal: bool,
    ) -> bool:
        """Predicate: should this pending signal collapse onto the prior group?

        Returns True when the most recent item is an empty assistant
        bubble for the same model — that's the signature of a retry
        cycle (prior attempt errored after its pending signal but
        before producing content). Caller reuses that group and
        increments its ``retries`` counter so the user sees one bubble
        across all attempts rather than a wall of empties.
        """
        if not (is_pending_signal and role == "assistant" and self.items):
            return False
        last = self.items[-1]
        if not isinstance(last, MessageGroup):
            return False
        if last.role != "assistant" or last.segments:
            return False
        model_hint = meta.get(MODEL_META_KEY)
        return not isinstance(model_hint, str) or last.model in (None, model_hint)

    def _apply_pending_lifecycle(
        self,
        group: MessageGroup,
        is_pending_signal: bool,
        meta: dict[str, Any],
    ) -> None:
        """Reconcile pending markers on the group.

        The router stamps explicit markers on the model-event boundary
        chunks: a ``pending`` marker on entry (status row flips to
        ``generating`` immediately) and a ``complete`` marker on exit
        when no real content was emitted (tool-only responses). Real
        content chunks also implicitly close the pending window — but
        that side of the lifecycle lives in :meth:`_append_segment`,
        since closure follows the moment content arrives.
        """
        if is_pending_signal:
            self._pending_message_ids.add(group.message_id)
            group.pending = True
            # Stamp the wall-clock start on the FIRST pending signal
            # so the chip's elapsed timer reflects total time across
            # any retries.
            if group.pending_started_at is None:
                group.pending_started_at = self._now()
        if meta.get(MODEL_EVENT_COMPLETE_META_KEY):
            self._pending_message_ids.discard(group.message_id)
            group.pending = False

    def _append_segment(
        self,
        group: MessageGroup,
        update: UserMessageChunk | AgentMessageChunk | AgentThoughtChunk,
    ) -> None:
        """Add chunk text to the group, extending the last segment if same kind.

        Adjacent chunks of the same kind extend the last segment so
        multi-chunk text streams as one block; a kind change (text →
        reasoning or vice versa) starts a new segment so the renderer
        can show interleaved thought / response in true arrival order.

        Also closes the pending window once real content arrives —
        generation has produced output, so the chip should drop its
        spinner regardless of whether the explicit complete marker
        has been seen yet.
        """
        text = self._text_from_content(update.content)
        if not text:
            return
        kind = self._segment_kind_for(update)
        if group.segments and group.segments[-1].kind == kind:
            group.segments[-1].text += text
        else:
            group.segments.append(Segment(kind=kind, text=text))
        # Real content closes the pending window — harmless no-op when
        # no pending was open (cache-hit path skips the pending phase).
        self._pending_message_ids.discard(group.message_id)
        group.pending = False

    def _apply_chunk_metadata(
        self,
        group: MessageGroup,
        role: MessageRole,
        meta: dict[str, Any],
    ) -> None:
        """Reconcile model attribution + user source from chunk meta."""
        # Assistant / reasoning chunks carry the originating
        # ModelEvent.model in ``_meta["inspect.model"]``; user chunks
        # have no model attribution.
        model = meta.get(MODEL_META_KEY)
        if isinstance(model, str) and model:
            group.model = model
            self.current_model = model
        # User source is stamped by the server (input / operator /
        # generate / null). First chunk wins — the server emits one
        # chunk per user message, but be defensive against future
        # changes by only setting when previously unset.
        if role in ("user", "system") and group.user_source is None:
            source = meta.get(USER_SOURCE_META_KEY)
            if isinstance(source, str) and source:
                group.user_source = source

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
        # ToolCallStart and ToolCallProgress share the same
        # first-sight / merge shape — see :meth:`_consume_tool_update`.
        return self._consume_tool_update(update)

    def _consume_tool_progress(self, update: ToolCallProgress) -> bool:
        # ToolCallProgress before ToolCallStart shouldn't happen on the
        # wire today (the server always emits start first) but is
        # treated symmetrically as a defensive fallback — synthesize a
        # card so the operator at least sees the in-flight tool.
        return self._consume_tool_update(update)

    def _consume_tool_update(self, update: ToolCallStart | ToolCallProgress) -> bool:
        """Apply an incoming tool update: create on first sight, merge thereafter.

        Both ToolCallStart and ToolCallProgress route through here. On
        first sight (no entry in the index) we construct the
        ToolCallState and append to ``items``; on subsequent updates
        we merge non-None fields per ACP's replace-on-present
        semantics. Either path can carry a terminal status so end_time
        is set during construction OR via the merge.
        """
        tc = self._tool_calls_by_id.get(update.tool_call_id)
        if tc is None:
            tc = self._create_tool_call_state(update)
            self._tool_calls_by_id[update.tool_call_id] = tc
            self.items.append(tc)
            return True
        self._merge_tool_fields(tc, update)
        return True

    def _create_tool_call_state(
        self, update: ToolCallStart | ToolCallProgress
    ) -> ToolCallState:
        """Build a fresh ToolCallState from the first update we see."""
        status = update.status or "in_progress"
        start_time = self._now()
        tc = ToolCallState(
            tool_call_id=update.tool_call_id,
            title=update.title,
            kind=update.kind,
            status=status,
            content=list(update.content) if update.content is not None else None,
            raw_input=update.raw_input,
            raw_output=update.raw_output,
            start_time=start_time,
        )
        # Terminal-on-first-sight (e.g. replay of a completed tool):
        # set end_time = start_time so duration reads as ~0 instead
        # of None.
        if tc.status in ("completed", "failed"):
            tc.end_time = start_time
        return tc

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

    # ------------------------------------------------------------------
    # Windowing
    # ------------------------------------------------------------------

    def _enforce_turn_cap(self) -> None:
        """Drop the oldest exchanges past the assistant-turn window.

        Cap is ``_MAX_ASSISTANT_TURNS`` *assistant* MessageGroups. Tool
        calls + user messages between kept assistants stay; earlier
        items are evicted from ``self.items`` and the lookup indexes
        so refreshes scale with the window size rather than the full
        history.

        The user message immediately preceding the oldest kept
        assistant is also retained when present — otherwise the
        windowed view reads as an orphaned response with no prompt
        context. Earlier user messages (those before that lookback)
        are dropped.
        """
        assistant_indices = [
            i
            for i, item in enumerate(self.items)
            if isinstance(item, MessageGroup) and item.role == "assistant"
        ]
        if len(assistant_indices) <= _MAX_ASSISTANT_TURNS:
            return
        keep_from = assistant_indices[-_MAX_ASSISTANT_TURNS]
        # Only extend backward if the IMMEDIATE predecessor is a user
        # message — i.e. that prompt clearly belongs to the same turn
        # as the first kept assistant. Walking further back risks
        # holding onto an irrelevant prompt from many turns ago (e.g.
        # the original react-style kickoff prompt with 20 assistant
        # steps trailing), which would defeat the cap entirely.
        if keep_from > 0:
            prev = self.items[keep_from - 1]
            if isinstance(prev, MessageGroup) and prev.role == "user":
                keep_from -= 1
        if keep_from <= 0:
            return
        dropped = self.items[:keep_from]
        del self.items[:keep_from]
        dropped_message_ids: set[str] = set()
        for item in dropped:
            if isinstance(item, MessageGroup):
                self._messages_by_id.pop(item.message_id, None)
                self._pending_message_ids.discard(item.message_id)
                dropped_message_ids.add(item.message_id)
            elif isinstance(item, ToolCallState):
                self._tool_calls_by_id.pop(item.tool_call_id, None)
        # Strip retry-collapse aliases that point at dropped groups —
        # leaving them would silently route future (rare, late)
        # chunks for those ids back into thin air.
        if dropped_message_ids:
            self._message_id_aliases = {
                k: v
                for k, v in self._message_id_aliases.items()
                if v not in dropped_message_ids
            }

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
    def has_active_work(self) -> bool:
        """Strict "is the agent currently doing something" signal.

        True iff a model event is pending or a tool call is in flight.
        Distinct from :attr:`status`, which also reports
        :attr:`StatusState.GENERATING` during the post-chunk quiescence
        window (the 2 seconds after the last chunk arrived).

        Used to gate operator-driven interrupt actions: ``Esc`` must
        only fire ``session/cancel`` when there's *actual* work to
        cancel, otherwise the server records a misleading
        ``between_turns`` ``InterruptEvent`` for the quiescence tail
        of a normal assistant response.
        """
        return bool(self._pending_message_ids) or self.tools_in_flight > 0

    @property
    def status(self) -> StatusState:
        """Current pill state derived from in-flight signal + quiescence.

        Order matters:
        - Any tool in flight → CALLING_TOOLS (clear signal, always wins)
        - Any pending model event → GENERATING (server signalled start,
          no completion marker yet — robust to long model latency)
        - Recent chunk activity → GENERATING (within quiescence window —
          covers the inter-chunk gap during active streaming)
        - Otherwise → AWAITING_INPUT (resting)
        """
        if self.tools_in_flight > 0:
            return StatusState.CALLING_TOOLS
        if self._pending_message_ids:
            return StatusState.GENERATING
        if self._last_chunk_at is not None:
            if (self._now() - self._last_chunk_at) < _GENERATING_QUIESCENCE_SECONDS:
                return StatusState.GENERATING
        return StatusState.AWAITING_INPUT
