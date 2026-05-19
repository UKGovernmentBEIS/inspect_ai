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

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal, Union

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    PlanEntry,
    RequestPermissionRequest,
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

    is_queued: bool = False
    """True for client-side ephemeral echoes of a not-yet-drained queued send.

    When the operator types into the composer and hits Enter while the
    agent is busy (``lifecycle != "idle"``), the message rides
    ``session/prompt`` into the server's ``submit_user_message`` queue
    and drains at the next ``before_turn``. Between those two moments
    the operator would otherwise see nothing — composer cleared, no
    transcript activity. The TUI mounts a queued ``MessageGroup`` in
    ``SessionState.items`` immediately on send so the operator sees
    their text echoed in place.

    Single-bucket semantics: at most ONE queued group exists at any
    time. Subsequent sends-while-busy APPEND to the existing group's
    text (with a ``\\n\\n`` paragraph separator) rather than stacking
    a new row. This mirrors the server-side
    ``_coalesce_operator_messages`` behavior — N queued sends drain
    as a single merged ``ChatMessageUser`` — so the visible ephemeral
    reflects exactly what the model will see. When the server's eventual
    ``UserMessageChunk(source="operator")`` arrives, the queued group
    is popped and the real merged group renders in its place.

    The chip reads ``user · queued`` and the body renders dim while
    this is True (see ``MessageWidget``). These groups are NOT
    registered in ``_messages_by_id`` / ``_pending_message_ids`` —
    they live solely in ``items`` and are managed by
    :meth:`SessionState.enqueue_queued_user_message` /
    :meth:`SessionState.undo_queued_enqueue`.
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


@dataclass(frozen=True)
class _QueuedEnqueueHandle:
    """Undo token returned from :meth:`SessionState.enqueue_queued_user_message`.

    Records the pre-enqueue state so :meth:`SessionState.undo_queued_enqueue`
    can roll back precisely:

    - ``prior_text=None`` ⇒ the enqueue created the ephemeral fresh;
      undo removes the whole group from :attr:`SessionState.items`.
    - ``prior_text=<str>`` ⇒ the enqueue appended to an existing
      ephemeral; undo restores ``group.segments[0].text`` to the
      snapshot.

    Frozen so callers can't accidentally mutate the snapshot before
    handing it back to undo.
    """

    group: MessageGroup
    prior_text: str | None


ToolCallStatus = Literal["pending", "in_progress", "completed", "failed"]

ApprovalDecisionLabel = Literal["approved", "denied", "cancelled"]
"""Post-resolution label shown in the tool card's decision-summary line.

Kept narrow: the actual ``ApprovalDecision`` (approve / reject / modify
/ terminate / escalate) is recorded server-side; the TUI only needs
to distinguish "the operator allowed it" vs. "denied it" vs. "we were
cancelled / interrupted before deciding".
"""


@dataclass
class PendingApproval:
    """An in-flight ACP ``session/request_permission`` awaiting a decision.

    Attached to a ``ToolCallState`` while the request is pending and
    cleared when the operator clicks an action (or :meth:`mark_complete`
    / :meth:`mark_interrupted` resolves it). The ``event`` lets the
    client-side JSON-RPC handler park on ``event.wait()`` until the
    button-press handler calls :meth:`SessionState.resolve_approval`,
    which sets the event and populates ``chosen_option_id`` (or the
    ``cancelled`` flag) for the handler to read.
    """

    request: RequestPermissionRequest
    event: asyncio.Event
    chosen_option_id: str | None = None
    cancelled: bool = False


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
    pending_approval: PendingApproval | None = None
    """The current pending ACP permission request, if any.

    Set by :meth:`SessionState.consume_approval_request` when a
    ``session/request_permission`` arrives for this tool call's id;
    cleared by :meth:`SessionState.resolve_approval` once the operator
    decides (or another client decides, or we get cancelled). The UI
    gates the inline approval section on ``pending_approval is not
    None`` — kept orthogonal to ``status`` so the existing
    pending/in_progress/completed/failed semantics don't change.
    """
    last_approval_decision: ApprovalDecisionLabel | None = None
    """The most recent decision, for the post-resolution summary line.

    Set when :meth:`SessionState.resolve_approval` clears
    ``pending_approval``. Persists for the lifetime of the card so the
    summary stays visible while the tool runs to completion below.
    """
    cancel_requested: bool = False
    """True once the operator has requested per-tool cancellation via ``^L``.

    Set by :class:`SessionScreen` before it fires the
    ``inspect/cancel_tool_call`` JSON-RPC request; consumed by the
    widget to append a dim ``cancelling…`` marker until the natural
    failure-status event lands and the card transitions to terminal.
    Doubles as an idempotence guard against double-fires —
    :class:`SessionState`'s ``cancel_tool_call_id`` accessor filters
    cards with this flag set so ``^L`` advances to the next eligible
    tool.
    """

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


_APPROVE_OPTION_IDS = frozenset({"approve", "modify"})
"""The ``ApprovalDecision`` ids that map to the ``approved`` summary label.

``option_id`` from the server is always one of the literal
:class:`ApprovalDecision` strings (set by ``_options_from_choices``
in ``approval/_human/acp.py``) — match those directly rather than
re-deriving from :class:`PermissionOption.kind`. ``approve`` is the
plain allow; ``modify`` is "approve with modification" which the
in-proc panel also treats as the allow half (see
``_KIND_BY_DECISION`` in the shim). Anything else (``reject`` /
``terminate`` / ``escalate``, or an unknown id from a misbehaving
client) maps to ``denied``.
"""


def _decision_label(
    *,
    option_id: str | None,
    cancelled: bool,
) -> ApprovalDecisionLabel:
    """Map a resolution outcome to the post-resolution summary label."""
    if cancelled:
        return "cancelled"
    if option_id in _APPROVE_OPTION_IDS:
        return "approved"
    return "denied"


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
        # Most recent plan from the server's ``AgentPlanUpdate`` stream
        # (collapsed plan-tool invocations for plan-rendering-capable
        # clients — see ``inspect_ext.PlanPolicyTransformer``). ACP plan
        # updates are full replacement, not deltas, so each new update
        # overwrites the list verbatim. ``None`` is distinct from ``[]``:
        # ``None`` means the agent has never emitted a plan and the strip
        # widget stays hidden; ``[]`` would mean the agent explicitly
        # cleared its plan (not produced by either Inspect planning tool
        # today, but reserved for forward-compat).
        self.plan_entries: list[PlanEntry] | None = None
        # Monotonic counter for locally-minted message ids on queued
        # ephemerals. Prefix ``queued-`` ensures the id never collides
        # with a server-minted one (UUIDv5 from a ModelEvent uuid).
        # See :attr:`MessageGroup.is_queued` for the queued ephemeral
        # lifecycle.
        self._queued_counter: int = 0
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
    def lifecycle(
        self,
    ) -> Literal["idle", "running", "interrupted", "approval", "complete"]:
        """Coarse-grained turn lifecycle for the header pill.

        Five states, in priority order so a true terminal signal
        always wins over transient turn state, and an operator-blocking
        approval beats general in-flight activity:

        - ``complete``: the server-side session has ended (transport
          disconnect / explicit end). Sticky — once set, stays set.
        - ``approval``: at least one tool call is awaiting an operator
          decision via ``session/request_permission``. Prioritized
          above ``running`` because the agent is genuinely blocked on
          us — the operator needs to know they're the holdup, not just
          that "something is happening".
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
        if self._has_pending_approval():
            return "approval"
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

    def _has_pending_approval(self) -> bool:
        """True iff any tool-call card holds an unresolved approval."""
        return any(
            tc.pending_approval is not None for tc in self._tool_calls_by_id.values()
        )

    def current_pending_approval(self) -> PendingApproval | None:
        """The first in-flight ``PendingApproval``, or ``None``.

        Drives the composer-area approval bar — only one approval is
        rendered at a time. Parallel tool calls each get their own
        ``ToolCallState.pending_approval`` slot; the bar shows them
        in insertion order (``_tool_calls_by_id`` is a regular
        dict). On resolve, the bar advances to the next pending.
        """
        for tc in self._tool_calls_by_id.values():
            if tc.pending_approval is not None:
                return tc.pending_approval
        return None

    def current_pending_tool_call_id(self) -> str | None:
        """The tool_call_id of the first in-flight approval, or ``None``.

        Sibling to :meth:`current_pending_approval` — the screen's
        binding handlers need this to call
        :meth:`resolve_approval`.
        """
        for tc_id, tc in self._tool_calls_by_id.items():
            if tc.pending_approval is not None:
                return tc_id
        return None

    def mark_complete(self) -> None:
        """Sticky-mark the session as ended (transport disconnect / end).

        Idempotent — subsequent calls are no-ops. Notifies subscribers
        on the first transition so the pill can flip immediately.

        Also resolves any still-pending approvals with
        ``cancelled=True`` so stale action buttons disappear from the
        post-completion read-only postmortem view. The client-side
        JSON-RPC handler task is being torn down (or already has been)
        by the disconnect / close, so its ``await pending.event.wait()``
        either already woke up cancelled OR is about to — either way
        the matching ``ToolCallState.pending_approval`` slot must be
        cleared so the lifecycle pill leaves ``approval`` and the
        inline section collapses to the ``⊘ cancelled`` summary line.

        Also drops any client-side queued ephemerals — the server
        won't drain them now, so leaving them mounted as dim ghost
        rows in the post-completion read-only view would mislead the
        operator into thinking those messages were delivered.
        """
        if self._complete:
            return
        self._complete = True
        # Batch the approval-cancel sweep with the sticky-complete
        # flip so subscribers only see ONE notification (lifecycle
        # ``complete``), not a flicker through whatever the
        # post-clear / pre-complete state would imply.
        self._clear_pending_approvals()
        self._drop_queued_user_messages()
        self._notify()

    def enqueue_queued_user_message(self, text: str) -> "_QueuedEnqueueHandle":
        r"""Mount or extend the client-side queued ephemeral.

        Called by :meth:`SessionScreen.action_submit` the moment the
        operator hits Enter while ``lifecycle != "idle"`` — the send
        will land in the server's ``submit_user_message`` queue and not
        surface back until the next ``before_turn`` drain. Without the
        echo the composer would clear silently and the operator would
        have no visible signal that their message registered.

        Single-bucket semantics: at most one queued group exists at any
        time. If one already exists, this APPENDS to its text with a
        ``\\n\\n`` paragraph separator (mirrors the server-side
        ``_coalesce_operator_messages`` merge — N queued sends drain
        as ONE merged ``ChatMessageUser``, so the visible row reflects
        exactly what the model will see). Otherwise creates a fresh
        queued group.

        Returns a :class:`_QueuedEnqueueHandle` that
        :meth:`undo_queued_enqueue` consumes on send failure — restores
        the prior text on the append path or removes the whole group on
        the fresh-creation path.

        Locally-minted ids (``queued-N``) never collide with the
        server's UUIDv5 ids; the group is NOT registered in
        ``_messages_by_id`` (so retry-collapse / drop-tombstone /
        turn-cap logic ignores it) — it lives only in :attr:`items`
        and is popped by an arriving operator chunk
        (:meth:`_consume_chunk`), :meth:`undo_queued_enqueue`, or
        :meth:`mark_complete`.
        """
        existing = self._current_queued_user_group()
        if existing is not None:
            # Append-on-existing — single segment, extend with paragraph
            # separator. Snapshot the prior text for undo.
            prior_text = existing.segments[0].text
            existing.segments[0].text = f"{prior_text}\n\n{text}"
            self._notify()
            return _QueuedEnqueueHandle(group=existing, prior_text=prior_text)
        # Fresh creation — no prior queued group.
        self._queued_counter += 1
        group = MessageGroup(
            message_id=f"queued-{self._queued_counter}",
            role="user",
            segments=[Segment(kind="text", text=text)],
            user_source="operator",
            is_queued=True,
        )
        self.items.append(group)
        self._notify()
        return _QueuedEnqueueHandle(group=group, prior_text=None)

    def undo_queued_enqueue(self, handle: "_QueuedEnqueueHandle") -> None:
        """Restore the queued ephemeral to its pre-enqueue state.

        Used by :meth:`SessionScreen.action_submit` when the
        ``session/prompt`` await raises — the server never accepted the
        message, so the optimistic append (or fresh creation) must come
        back out. Idempotent: replaying the same undo, or undoing a
        group that's since been popped by an arriving chunk, is a
        silent no-op.

        On a fresh-creation handle (``prior_text is None``), removes
        the whole group from :attr:`items`. On an append-on-existing
        handle, restores ``segments[0].text`` to the pre-append
        snapshot — preserving any earlier queued sends.
        """
        if handle.group not in self.items:
            return
        if handle.prior_text is None:
            # Fresh creation — drop the group entirely.
            self.items.remove(handle.group)
            self._notify()
        else:
            # Append-on-existing — restore prior text.
            handle.group.segments[0].text = handle.prior_text
            self._notify()

    def _current_queued_user_group(self) -> MessageGroup | None:
        """Return the in-flight queued ephemeral, or ``None``.

        Single-bucket invariant: at most one queued group at any time
        (subsequent ``enqueue`` calls append to the existing one). This
        accessor scans :attr:`items` linearly — typical sample length
        is tens of items so the cost is negligible.
        """
        for item in self.items:
            if isinstance(item, MessageGroup) and item.is_queued:
                return item
        return None

    def _pop_queued_user_group(self) -> bool:
        """Pop THE queued ephemeral from :attr:`items` (single-bucket).

        Called inside :meth:`_consume_chunk` when an operator-sourced
        ``UserMessageChunk`` arrives: the server has drained our (single)
        coalesced queued message, so the client-side echo is replaced by
        the real group that the chunk will create immediately after.

        Returns True iff a queued entry was popped. No notify here —
        the caller (``_consume_chunk``) batches the pop with the
        regular chunk-consumption notify so subscribers see one
        coherent update.
        """
        for idx, item in enumerate(self.items):
            if isinstance(item, MessageGroup) and item.is_queued:
                del self.items[idx]
                return True
        return False

    def _drop_queued_user_messages(self) -> None:
        """Remove every queued ephemeral. No notify — caller batches."""
        self.items = [
            item
            for item in self.items
            if not (isinstance(item, MessageGroup) and item.is_queued)
        ]

    def mark_interrupted(self) -> None:
        """Optimistically clear in-flight signals after the operator hits Esc.

        The cancel notification round-trips through the server (agent
        loop unwind → transcript update → router emit → wire back), so
        the spinner / status pill would otherwise stay on
        ``GENERATING`` or ``CALLING_TOOLS`` for the full propagation
        window. Clearing locally gives instant feedback; if the model
        actually produces content before the cancel lands, the next
        chunk just re-establishes pending state honestly.

        Five things change:
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
        - any pending approvals are resolved with
          ``cancelled=True``. Without this, an Esc during a
          pending approval would leave the client-side JSON-RPC
          handler parked on ``PendingApproval.event`` (so the
          server's request future never resolves) AND leave the
          inline section's action buttons visible on a card the
          operator just told us to abandon. Esc means "stop
          what's happening" — that includes the approval.
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
        # Resolve any in-flight approvals as cancelled — same
        # rationale as ``mark_complete``. Goes through the no-notify
        # batch helper so we can flip ``_interrupted`` below in the
        # SAME tick; otherwise the per-approval notify would expose
        # a transient ``lifecycle == 'idle'`` to subscribers (pending
        # cleared, ``_interrupted`` not yet True).
        if self._clear_pending_approvals():
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
        elif isinstance(update, AgentPlanUpdate):
            changed = self._consume_plan_update(update)
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

    # ------------------------------------------------------------------
    # Approval handshake
    # ------------------------------------------------------------------
    #
    # An incoming ``session/request_permission`` request takes a
    # different path from notifications — it's an inbound RPC the
    # client must respond to. The client.py handler validates the
    # request, parks on a ``PendingApproval.event``, and waits for the
    # operator to click an action. ``consume_approval_request`` and
    # ``resolve_approval`` are the two halves of that handshake on the
    # state side. The asyncio.Event handshake mirrors the in-proc
    # ``human_approval_manager`` pattern (``approval/_human/panel.py``).

    def mark_cancel_requested(self, tool_call_id: str) -> bool:
        """Flag a tool card as cancel-requested; returns True iff anything changed.

        Sets ``ToolCallState.cancel_requested`` for the named tool and
        notifies subscribers so the widget's footer flips to
        ``cancelling…`` immediately. Returns False (no-op, no notify)
        when the tool is unknown, already terminal, already
        cancel-requested, or awaiting an operator approval decision
        (the approval bar's reject / terminate is the right exit
        there). Idempotence guard against rapid ``^L`` repeats —
        callers can fire-and-forget the JSON-RPC request only when
        this method returns True.
        """
        tc = self._tool_calls_by_id.get(tool_call_id)
        if tc is None or tc.is_terminal or tc.cancel_requested:
            return False
        if tc.pending_approval is not None:
            return False
        tc.cancel_requested = True
        self._notify()
        return True

    def clear_cancel_requested(self, tool_call_id: str) -> bool:
        """Undo a prior ``mark_cancel_requested``; returns True iff anything changed.

        Used when the cancel RPC fails (exception) or the server
        reports ``{cancelled: false}`` — both cases mean the operator's
        intent didn't take effect, so the footer should return to its
        normal in-flight rendering and ``^L`` should be retargetable
        for the tool (the ``cancel_tool_call_id`` accessor filters
        cancel-requested tools out of the eligibility set, so without
        this clear the operator has no retry path).

        No-op for unknown tools or tools that aren't flagged —
        returns False, no notify. Cleaning the flag on a now-terminal
        tool is harmless but pointless; the accessor filters by
        ``is_terminal`` independently.
        """
        tc = self._tool_calls_by_id.get(tool_call_id)
        if tc is None or not tc.cancel_requested:
            return False
        tc.cancel_requested = False
        self._notify()
        return True

    def consume_approval_request(self, pending: PendingApproval) -> None:
        """Attach a pre-built ``PendingApproval`` to the matching tool-call card.

        The caller (typically the client-side ``session/request_permission``
        handler) owns the ``PendingApproval`` and reads its
        ``chosen_option_id`` / ``cancelled`` flags AFTER awaiting
        ``pending.event``. By passing the object
        in (rather than letting state synthesize it from
        ``(request, event)``) the handler keeps the same reference
        that :meth:`resolve_approval` mutates — single source of truth
        for the resolution outcome.

        Permission requests fire BEFORE the tool executes, so the
        matching ``ToolCallStart`` may not have arrived yet. In that
        case we synthesize a card from the request's ``tool_call``
        payload (which already carries title, kind, raw_input, content
        per the server-side ``_build_request``); the later
        ``ToolCallStart`` merges in via the normal
        ``_consume_tool_update`` path.
        """
        tool_call_id = pending.request.tool_call.tool_call_id
        tc = self._tool_calls_by_id.get(tool_call_id)
        if tc is None:
            tc = self._tool_call_state_from_request(pending.request)
            self._tool_calls_by_id[tool_call_id] = tc
            self.items.append(tc)
        tc.pending_approval = pending
        self._notify()

    def resolve_approval(
        self,
        tool_call_id: str,
        *,
        option_id: str | None = None,
        cancelled: bool = False,
    ) -> None:
        """Resolve a pending approval; fires the event so the handler returns.

        Idempotent: re-resolving an already-resolved approval is a
        no-op (button double-click safety). The decision is recorded
        on ``last_approval_decision`` for the post-resolution summary
        line, then ``pending_approval`` is cleared.

        Pass ``option_id`` for an operator-driven decision (the literal
        ``ApprovalDecision`` string round-tripped from the wire), or
        ``cancelled=True`` for unmount / disconnect / Esc / session
        completion — the handler reads the ``PendingApproval`` flags
        set here to build its wire response.
        """
        if self._resolve_approval_inner(
            tool_call_id, option_id=option_id, cancelled=cancelled
        ):
            self._notify()

    def _resolve_approval_inner(
        self,
        tool_call_id: str,
        *,
        option_id: str | None = None,
        cancelled: bool = False,
    ) -> bool:
        """Mutate-only resolve. Returns True if anything changed.

        Used by :meth:`resolve_approval` (which notifies after) and
        by bulk-transition helpers like :meth:`_clear_pending_approvals`
        that batch many resolves into a single ``_notify()``. Keeps the
        bulk path from firing intermediate notifications that briefly
        expose an inconsistent lifecycle to subscribers (e.g. ``Esc``
        clearing approvals BEFORE ``_interrupted`` flips would otherwise
        let one subscriber observation slip through with
        ``lifecycle == 'idle'``).

        Fires ``pending.event`` here so the parked JSON-RPC handler
        wakes immediately — the wire response is unrelated to the
        UI-refresh notification.
        """
        tc = self._tool_calls_by_id.get(tool_call_id)
        if tc is None or tc.pending_approval is None:
            return False
        pending = tc.pending_approval
        pending.chosen_option_id = option_id
        pending.cancelled = cancelled
        tc.last_approval_decision = _decision_label(
            option_id=option_id,
            cancelled=cancelled,
        )
        tc.pending_approval = None
        pending.event.set()
        return True

    def _clear_pending_approvals(self) -> bool:
        """Resolve every in-flight approval as cancelled, NO notify.

        Returns True if any approvals were cleared. Used by
        :meth:`mark_complete` and :meth:`mark_interrupted` so they
        can batch the approval-cancel sweep alongside their other
        mutations and fire ``_notify()`` exactly once at the end.
        Without this, the per-call notifies inside ``resolve_approval``
        would fire mid-transition (before ``_interrupted`` /
        ``_complete`` is set) and subscribers would briefly observe a
        lifecycle that doesn't reflect what's about to happen.
        """
        any_cleared = False
        for tc in list(self._tool_calls_by_id.values()):
            if tc.pending_approval is not None and self._resolve_approval_inner(
                tc.tool_call_id, cancelled=True
            ):
                any_cleared = True
        return any_cleared

    def _tool_call_state_from_request(
        self,
        request: RequestPermissionRequest,
    ) -> ToolCallState:
        """Synthesize a card from a pre-execution permission request.

        The ``ToolCallUpdate`` inside the request carries title /
        kind / raw_input — these become the card's identity. We
        deliberately do NOT copy ``tu.content`` into ``tc.content``:
        the inline approval section already renders the request's
        content blocks directly (assistant message + view halves +
        separator), and ``_compose_body`` would otherwise render the
        same blocks again under the section. ``content`` stays
        ``None`` until the eventual ``ToolCallStart`` arrives with
        the actual tool-input view (typically the same view, but it
        belongs in the body, not duplicated above it).

        ``status`` is normalized to ``"pending"`` since that's what
        the request declares (and what the server's ``_build_request``
        sets).
        """
        tu = request.tool_call
        status: ToolCallStatus = (
            tu.status if tu.status in ("pending", "in_progress") else "pending"
        )
        return ToolCallState(
            tool_call_id=tu.tool_call_id,
            title=tu.title,
            kind=tu.kind,
            status=status,
            content=None,
            raw_input=tu.raw_input,
            raw_output=tu.raw_output,
            start_time=self._now(),
        )

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

        # Operator-sourced user chunks consume the (single) queued
        # ephemeral before the real group is created — the server has
        # drained our queued send (coalesced server-side into one
        # ``ChatMessageUser``) and this chunk IS its server echo. The
        # pop and the real group's append happen in the same
        # ``consume()`` tick so subscribers see a single swap, not a
        # transient "ephemeral disappeared, real not yet present" frame.
        # See :attr:`MessageGroup.is_queued` for the lifecycle.
        if role == "user" and meta.get(USER_SOURCE_META_KEY) == "operator":
            self._pop_queued_user_group()

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
        - retry-collapse hit (see :meth:`_find_retry_collapse_target`) →
          reuse the prior empty assistant bubble, bump ``retries``,
          alias the new id, drop the stale pending tracking.
        - otherwise → create a fresh group, register it, enforce the
          assistant-turn window cap.
        """
        existing = self._messages_by_id.get(message_id)
        if existing is not None:
            return existing
        prior = self._find_retry_collapse_target(role, meta, is_pending_signal)
        if prior is not None:
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

    def _find_retry_collapse_target(
        self,
        role: MessageRole,
        meta: dict[str, Any],
        is_pending_signal: bool,
    ) -> MessageGroup | None:
        """Locate the empty assistant bubble this pending signal should collapse onto.

        Returns the prior :class:`MessageGroup` when the most recent
        non-queued item is an empty assistant bubble for the same model
        — that's the signature of a retry cycle (prior attempt errored
        after its pending signal but before producing content). Caller
        reuses that group, increments ``retries``, aliases the new id,
        and drops the stale pending tracking. Returns ``None`` in any
        other shape (no pending signal, no assistant, no items, the
        prior non-queued item already has content, or the model
        attribution doesn't match).

        **Queued ephemerals are transparent.** A client-side queued
        ``MessageGroup(is_queued=True)`` may sit at ``items[-1]`` between
        the prior empty assistant bubble and the retry's pending signal
        (the operator typed a message while the first attempt was in
        flight). Walking backward and skipping queued entries finds the
        real retry-collapse target; without the skip, the prior pending
        id would never get its completion marker and the lifecycle pill
        would stay on ``running`` forever after the retry succeeded.
        """
        if not (is_pending_signal and role == "assistant" and self.items):
            return None
        for item in reversed(self.items):
            # Queued ephemerals are client-side display state, not
            # model output — invisible to the retry-collapse decision.
            if isinstance(item, MessageGroup) and item.is_queued:
                continue
            # Apply the original retry-collapse criteria to the first
            # non-queued item: must be an empty assistant bubble of
            # the same model.
            if not isinstance(item, MessageGroup):
                return None
            if item.role != "assistant" or item.segments:
                return None
            model_hint = meta.get(MODEL_META_KEY)
            if isinstance(model_hint, str) and item.model not in (None, model_hint):
                return None
            return item
        return None

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

    def _consume_plan_update(self, update: AgentPlanUpdate) -> bool:
        # Full replacement (ACP plan updates are not deltas). Copy the
        # list so the caller's PlanEntry instances are decoupled from
        # ours — guards against later mutation by the schema layer or
        # by accident in a test.
        self.plan_entries = list(update.entries)
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
    def cancel_tool_call_id(self) -> str | None:
        """``tool_call_id`` of the tool ``^L`` would currently cancel, or None.

        Eligibility: in-flight (``pending`` / ``in_progress``), not
        awaiting an operator approval decision (the approval bar's
        ``reject`` / ``terminate`` is the right exit there), and not
        already cancel-requested (so a second ``^L`` advances to the
        next eligible tool instead of re-firing on the one we just
        cancelled). Among eligible tools, the most-recently-started
        wins — that's the card the operator is most likely watching
        at the bottom of the transcript.

        Used by :class:`SessionScreen` to resolve the ``^L`` binding
        and by ``check_action`` to decide whether the screen-footer
        ``cancel tool`` hint should be visible.
        """
        eligible = [
            tc
            for tc in self._tool_calls_by_id.values()
            if tc.status in ("pending", "in_progress")
            and tc.pending_approval is None
            and not tc.cancel_requested
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda tc: tc.start_time).tool_call_id

    @property
    def plan_done_count(self) -> int:
        """Completed-entry count for the current plan, or 0 if no plan."""
        if self.plan_entries is None:
            return 0
        return sum(1 for entry in self.plan_entries if entry.status == "completed")

    @property
    def plan_total_count(self) -> int:
        """Total-entry count for the current plan, or 0 if no plan."""
        if self.plan_entries is None:
            return 0
        return len(self.plan_entries)

    @property
    def plan_current_entry(self) -> PlanEntry | None:
        """First non-completed plan entry — what the strip surfaces as "current".

        Prefers an in-progress entry over a pending one if both exist
        (an agent that explicitly marks one row as the active focus
        should win over the first pending). Returns ``None`` when
        there's no plan or every entry is completed.
        """
        idx = self.plan_current_index
        if idx is None:
            return None
        # plan_current_index already implies plan_entries is non-empty.
        assert self.plan_entries is not None
        return self.plan_entries[idx]

    @property
    def plan_current_index(self) -> int | None:
        """Index of the plan row the operator should focus on.

        Single source of truth for "what's current" — used by the
        strip's body formatter (via :attr:`plan_current_entry`) AND
        by the overlay's auto-scroll. Both surfaces must agree, so
        defining the selection logic once here avoids the strip
        saying "current: B" while the overlay opens on row A.

        Rule: prefer an explicitly ``in_progress`` row over the first
        ``pending``. The agent sets one row ``in_progress`` to mark
        the active focus; that should always win.
        """
        if not self.plan_entries:
            return None
        for i, entry in enumerate(self.plan_entries):
            if entry.status == "in_progress":
                return i
        for i, entry in enumerate(self.plan_entries):
            if entry.status != "completed":
                return i
        return None

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
