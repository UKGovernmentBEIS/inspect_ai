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
    ElicitationSchema,
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
    REPLAY_META_KEY,
    TOOL_CALL_CANCELABLE_META_KEY,
    TOTAL_MESSAGES_META_KEY,
    USER_SOURCE_META_KEY,
)
from inspect_ai.scorer._metric import CORRECT, INCORRECT, NOANSWER, PARTIAL
from inspect_ai.util._span import SCORER_SPAN_TYPE, SCORERS_SPAN_NAME

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


ElicitationAction = Literal["accept", "decline", "cancel"]
"""Action submitted by the operator in response to an elicitation card.

Mirrors ACP's ``elicitation/create`` response discriminator.
``cancel`` is used for the implicit cancellation paths (session
teardown, sample interrupt) — the operator never picks it from a
button.
"""


@dataclass
class PendingElicitation:
    """An in-flight ACP ``elicitation/create`` awaiting a submission.

    Held on :class:`SessionState` (one at a time — the agent loop
    issues one ``ask_user`` call at a time) while the inline form
    card is visible. The ``event`` lets the client-side JSON-RPC
    handler park on ``event.wait()`` until the card's Submit /
    Decline button (or one of the cancel paths via
    :meth:`mark_complete` / :meth:`mark_interrupted`) calls
    :meth:`SessionState.resolve_elicitation`, which sets the event
    and populates ``action`` + ``content`` for the handler to read.

    Bare-minimum design for Phase 6a — Phase 6b will extract a
    reusable inline-card primitive that may carry additional metadata
    (timeouts, retries, etc.); for now we mirror :class:`PendingApproval`
    one-for-one.
    """

    message: str
    requested_schema: ElicitationSchema
    event: asyncio.Event
    tool_call_id: str | None = None
    action: ElicitationAction | None = None
    content: dict[str, Any] | None = None


@dataclass
class PendingCancel:
    """An operator-initiated sample-cancel awaiting disposition.

    Set on :class:`SessionState.pending_cancel` when the operator
    invokes ``^N`` on the session screen; the inline
    :class:`_CancelCard` mounts to render the choice and the screen
    enters auto-follow mode so the card stays visible as new events
    arrive (the agent keeps running while the operator deliberates —
    see ``design/acp/elicitation.md`` "Routing policy" + Phase 6b
    plan for the rationale).

    Carries the JSON-RPC plumbing the card needs to fire
    ``inspect/cancel_sample`` directly when Score / Error is picked:
    the operator's pick → RPC → on success the screen flips
    ``mark_sample_cancelling`` to start the local in-flight cleanup,
    and the natural ``inspect/session_ended`` flow handles the
    terminal-state transition. ``Back`` is a fire-free no-op that
    just clears the slot.

    Bare-minimum design for Phase 6b — see the slot helpers
    :meth:`SessionState.consume_cancel_request` and
    :meth:`SessionState.resolve_cancel`.
    """

    fails_on_error: bool
    # The bound ACP connection — typed as ``Any`` to avoid a circular
    # import through ``acp.connection``. The card calls
    # ``connection.send_request(INSPECT_CANCEL_SAMPLE_METHOD, …)``.
    connection: Any
    session_id: str


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
    cancelable: bool = True
    """Whether ``inspect/cancel_tool_call`` can act on this tool.

    False for bridged agents' tool calls (carried via
    ``TOOL_CALL_CANCELABLE_META_KEY`` on the ``ToolCallStart``): the bridged
    scaffold runs the tool, so there's no pending ``ToolEvent`` to cancel and the
    request would no-op. The ``cancel_tool_call_ids`` accessor filters these out
    so the per-tool cancel affordance isn't offered (turn-level interrupt still
    works). Absent meta ⇒ True (the react default).
    """
    parallel_batch_id: int | None = None
    """Sticky id of the parallel batch this tool joined, or None for solo tools.

    Set by :meth:`SessionState._tag_parallel_batch` whenever ≥2 tools
    are simultaneously eligible-in-progress (in_progress, not pending
    approval, not cancel-requested) — both the existing and the newly
    arriving tools get tagged with a shared id. A new tool that starts
    while another already-tagged tool is still running inherits that
    tool's batch id; a new batch (no overlap with any tagged
    in-progress tool) allocates a fresh id. Never cleared.

    Drives the deferred-body parallel-tools gate in
    :class:`TranscriptWidget._compute_defer_body`: a tool keeps its
    body held back until every member of *its own* batch has reached
    a terminal status. Scoping by batch id (rather than a global
    "any parallel tool still running" sweep) prevents a later batch
    from re-deferring the bodies of an earlier, already-settled
    batch's tools.
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


@dataclass
class ScoreChip:
    """An inline transcript chip for an emitted ``ScoreEvent``.

    Mid-stream rendering of scoring outcomes (mockup 02e). Mounted at
    the current end-of-transcript position when an ``inspect/event``
    notification for a ``ScoreEvent`` arrives, alongside message groups
    and tool calls. Retention follows the existing turn-cap: chips
    anchored before the surviving message-group window are evicted in
    the same sweep as their surrounding turns (see
    :meth:`SessionState._enforce_turn_cap`).
    """

    scorer: str | None
    value: str
    passed: bool | None
    """``True`` for the canonical "correct" CORRECT score (``"C"``);
    ``False`` for ``"I"`` (incorrect); ``None`` for numeric / other
    non-binary scores where pass/fail isn't meaningful."""

    reason: str | None
    chip_id: str
    """Locally-minted unique id so the transcript widget keys its
    mounted entry without colliding with message_id or
    tool_call_id."""

    answer: str | None = None
    """The model's answer for this score (``Score.answer``), shown as
    an ``answer: <answer>`` line above the explanation when non-empty.
    Indicator chips and chips whose underlying score didn't carry an
    answer leave this ``None``."""

    span_id: str | None = None
    """Transcript span id of the scorer that produced (or is producing)
    this chip. Set on the per-scorer ``scoring · X…`` indicator chips
    mounted off ``span_begin(type="scorer")`` so the matching
    ``span_end`` can identify and remove its indicator without needing
    a separate tracking field on the surrounding state."""

    started_at: float | None = None
    """``time.monotonic()`` reading captured when an indicator chip was
    first mounted. Drives the live ``Ns`` elapsed timer the widget
    renders alongside the in-flight spinner — same pattern the
    assistant chip uses for its pending-generation timer. Only set on
    indicator chips; real score chips leave this ``None`` because
    they're terminal and have nothing to tick."""

    scorer_name: str | None = None
    """Human-readable scorer name on indicator chips (e.g.
    ``"includes"``). The indicator's ``reason`` field still carries
    the ``"scoring · <name>…"`` text for back-compat / fallback
    rendering, but the widget prefers this field so the per-tick
    re-render can format ``score · <name> · 12s`` without re-parsing
    the reason string each frame."""


EventChipKind = Literal["sample_limit", "error", "compaction", "info"]
"""Inspect-native transcript events the TUI renders as inline event chips.

Score events have their own dedicated :class:`ScoreChip` because of
the per-scorer indicator flow; the four kinds here all share the same
"colored glyph + header + optional body" treatment so a single
dataclass + widget pair covers them."""


@dataclass
class EventChip:
    """An inline transcript chip for an Inspect-native transcript event.

    Mounted at the current end-of-transcript position when an
    ``inspect/event`` notification for one of :data:`EventChipKind`
    arrives. Pre-formatted header + body keeps the widget dumb
    (renders, doesn't decide what to show); per-event extraction lives
    in :class:`SessionState`'s ``consume_*_event`` builders where it's
    testable as pure functions.
    """

    kind: EventChipKind
    """Which Inspect event family this chip represents. Drives the
    widget's per-kind glyph + colour + background tint."""

    header_summary: str
    """The full chip header text after the leading glyph — e.g.
    ``"limit · token"`` or ``"compaction · summary · tokens 12k → 4k"``.
    Built by the per-event builder so the widget doesn't need
    per-kind formatting logic."""

    body_text: str | None
    """Optional body to render under the header. ``None`` skips the
    body block entirely (the chip renders as header-only).
    :class:`ErrorEvent` puts ``error.message`` here; the traceback
    rides ``traceback`` separately so the widget can give it its own
    click-to-expand affordance."""

    chip_id: str
    """Locally-minted unique id so the transcript widget keys its
    mounted entry without colliding with message_id, tool_call_id, or
    score chip ids."""

    traceback: str | None = None
    """Only populated for ``kind == "error"``. Rendered behind a
    click-to-expand ``traceback`` link below the body text — the same
    UX :class:`_ReasoningBlock` uses for reasoning content. Plain text
    (``EvalError.traceback``), not the ANSI variant; ANSI parsing in
    the TUI is a bigger lift than this phase warrants."""

    body_format: Literal["markdown", "json", "plain"] = "markdown"
    """How the widget should render ``body_text``.

    - ``"markdown"`` (default) — pipe through :class:`StyledMarkdown`
      via :class:`CollapsibleContent`. Markdown formatting (``**``,
      lists, fenced code blocks) renders inline.
    - ``"json"`` — pipe through :class:`rich.json.JSON` for syntax-
      highlighted JSON *without* the markdown code-block background
      tint. Used by :class:`InfoEvent` bodies whose ``data`` payload
      is structured (dict / list) so the JSON inherits the chip's
      manila card band instead of stamping its own dark code-block
      rectangle on top.
    - ``"plain"`` — render the raw text as-is in a simple ``Static``
      with no Markdown pipeline. Used by :class:`ErrorEvent` bodies
      (exception messages), which are not authored Markdown and
      where the Markdown layer's paragraph spacing introduced a
      visual gap between the chip header and the message text.
    """


TranscriptItem = Union[MessageGroup, ToolCallState, ScoreChip, EventChip]


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


def _format_score_value(value: Any) -> str:
    """Render a score's ``value`` field as a compact display string.

    Mirrors :meth:`Score.as_str` for scalars; falls back to ``repr``
    for non-scalar shapes (list / dict) so the chip still has a useful
    label without truncating wide structures inline.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return repr(value)


def _value_to_float(value: Any) -> float | None:
    """Emulate :func:`inspect_ai.scorer.value_to_float`'s scalar mapping.

    Returns ``None`` for inputs the upstream function would log-and-
    default to ``0.0`` (unrecognised strings, lists, dicts, ``None``).
    The chip surfaces those as "no float available" so the widget can
    render a neutral marker instead of misclaiming a definitive zero.

    Always uses the canonical sentinels (``"C"`` / ``"I"`` / ``"P"`` /
    ``"N"``); custom-sentinel scorers are rare and the chip's visual
    treatment doesn't benefit from per-call configuration.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if value == CORRECT:
            return 1.0
        if value == PARTIAL:
            return 0.5
        if value == INCORRECT or value == NOANSWER:
            return 0.0
        lowered = value.lower()
        if lowered in ("yes", "true"):
            return 1.0
        if lowered in ("no", "false"):
            return 0.0
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _classify_score_value(value: Any) -> bool | None:
    """Return ``True`` only when the score is an unambiguous pass.

    "Unambiguous pass" = :func:`_value_to_float` returns exactly
    ``1.0``. Everything else — partial credit, explicit zero, numeric
    values between 0 and 1, lists, dicts, unparseable strings —
    returns ``None`` and renders as a neutral chip. We deliberately
    don't emit ``False``: a partial score isn't a failure, and a
    plain ``0`` could mean different things in different rubrics, so
    the chip refrains from claiming a failure verdict it can't prove.
    Matches how the react agent reports scoring outcomes — a clean
    pass is celebrated, anything else is just "score landed".
    """
    float_val = _value_to_float(value)
    if float_val is None:
        return None
    return True if float_val == 1.0 else None


def _format_token_count(count: int) -> str:
    """Compact ``12345`` → ``12.3k`` rendering for token deltas.

    Used in the :class:`CompactionEvent` chip header so the operator
    can read "tokens 12.3k → 4.1k" without parsing seven-digit
    numbers in a one-line chip. Below 1k we render the raw count;
    above we collapse to one decimal of thousands.
    """
    if count < 1000:
        return str(count)
    return f"{count / 1000:.1f}k"


def _format_limit_value(limit_type: Any, value: float) -> str:
    """Render the numeric ``SampleLimitEvent.limit`` for the chip header.

    Type-specific so the unit reads correctly at a glance:

    - ``token``: thousands-compact (``100.0k``), shared with
      :func:`_format_token_count`.
    - ``time`` / ``working``: seconds (``60s``).
    - ``cost``: dollars to two decimals (``$5.50``).
    - everything else (``message`` / ``operator`` / ``custom``):
      integer when whole, otherwise two decimals.
    """
    if limit_type == "token":
        return _format_token_count(int(value))
    if limit_type in ("time", "working"):
        return f"{int(value)}s" if value.is_integer() else f"{value:.1f}s"
    if limit_type == "cost":
        return f"${value:.2f}"
    return f"{int(value)}" if value.is_integer() else f"{value:.2f}"


def _format_info_data(data: Any) -> tuple[str | None, Literal["markdown", "json"]]:
    """Render an :class:`InfoEvent` ``data`` payload for the chip body.

    Returns ``(body_text, body_format)`` so the widget knows which
    renderer to use:

    - Strings → markdown (assumed safe by the source).
    - Other JSON shapes (dicts, lists, scalars) → JSON. Returned as
      raw indented JSON text (no markdown fencing) so the widget can
      pipe it through :class:`rich.json.JSON` for syntax-highlighted
      rendering on the chip's own background, rather than markdown's
      fenced code block which stamps its own dark rectangle.
    - ``None`` / missing data → ``(None, "markdown")``; the chip
      renders header-only.
    """
    if data is None:
        return None, "markdown"
    if isinstance(data, str):
        text = data.strip()
        return (text if text else None), "markdown"
    try:
        import json

        rendered = json.dumps(data, indent=2, default=str)
    except (TypeError, ValueError):
        rendered = repr(data)
    return rendered, "json"


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
    messages: int = 0


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
        # In-flight ACP ``elicitation/create`` request, if any. Set by
        # :meth:`consume_elicitation_request` when the wire handler
        # accepts one; cleared by :meth:`resolve_elicitation` once the
        # operator submits / declines / one of the cancel paths fires.
        # Only one at a time — the agent loop issues at most one
        # ``ask_user`` tool call concurrently. The session screen reads
        # this slot to mount / unmount the inline elicitation card.
        self.pending_elicitation: PendingElicitation | None = None
        # Operator-initiated cancel-sample request, if any. Set by
        # :meth:`consume_cancel_request` when the screen's ``^N`` action
        # fires; cleared by :meth:`resolve_cancel` once the operator
        # picks Back / Score / Error. The session screen reads this slot
        # to mount / unmount the inline cancel card and to engage
        # auto-follow mode (the agent keeps running while the operator
        # deliberates — see the Phase 6b plan).
        self.pending_cancel: PendingCancel | None = None
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
        # Sticky flag flipped True the first time we see the outer
        # ``span(name="scorers")`` boundary. Suppresses any later
        # ``AgentPlanUpdate`` (typically a stale one from semantic
        # replay during late-attach: raw replay clears the plan via
        # the scorers boundary, then semantic replay would re-mount
        # the historical plan that was active mid-agent and the
        # operator would see the plan resurrect after scoring had
        # already finished). One-way: a fresh sample on a fresh
        # session gets a fresh ``SessionState``.
        self._scoring_started: bool = False
        # Sticky flag flipped True by ``mark_sample_cancelling`` after
        # the operator picks a disposition on the ^N cancel-sample bar.
        # Holds the lifecycle pill on ``running`` between the
        # operator's choice and the server's ``inspect/session_ended``
        # notification (which flips ``_complete`` to True). Without it
        # the optimistic in-flight cleanup would drop the lifecycle to
        # ``idle`` (or briefly ``interrupted``) even though the sample
        # is still being torn down server-side — scoring / finalize
        # are still running and the operator's choice was "wind this
        # down", not "interrupt this turn". ``_complete`` wins in the
        # lifecycle resolution so this flag doesn't need explicit
        # clearing on session end.
        self._cancelling: bool = False
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
        # Monotonic counter for locally-minted score-chip ids. Score
        # events don't carry stable client-side identity (each chip is
        # one in-place rendering of a server-emitted ``ScoreEvent``), so
        # we mint a fresh id per chip — used by the transcript widget
        # to key its mounted entry.
        self._score_chip_counter: int = 0
        # Monotonic counter for locally-minted event-chip ids (used by
        # the four :class:`EventChipKind` variants). Same rationale as
        # ``_score_chip_counter`` — the server-side events don't carry
        # an identifier we can reuse for the transcript widget key
        # (the ``uuid`` on ``BaseEvent`` is consumed by the dedup set
        # above, but the widget key wants a slug we mint locally so
        # the keying scheme is uniform across all chip types).
        self._event_chip_counter: int = 0
        # Currently-mounted ``scoring · X…`` indicator chip, if any.
        # Per-scorer: each ``span_begin(type=SCORER_SPAN_TYPE)`` mounts
        # a fresh indicator naming the scorer; whichever of the next
        # ``ScoreEvent`` OR matching ``span_end`` arrives first removes
        # it. At most one indicator is live at a time — scorers run
        # sequentially in the task runner's loop, so a fresh begin
        # always lands after the previous one resolved. Tracked by
        # reference so the removal path is O(items) but bounded by the
        # indicator's own lifetime. The originating span id is carried
        # on the chip itself (``ScoreChip.span_id``) so
        # ``_consume_span_end`` can recognise its own scorer's closing
        # event without a separate tracking field on this state object.
        self._scoring_indicator: ScoreChip | None = None
        # Transient (non-sticky) flag flipped True by ``mark_disconnected``
        # and False by ``mark_reconnected``. Orthogonal to ``lifecycle``:
        # connection state is about *transport* health while lifecycle
        # describes *agent-side* activity. The header's connection
        # indicator dot reads this; the composer's send guard reads
        # this. NOT folded into ``lifecycle`` because the agent may
        # still be "running" from the operator's POV while we briefly
        # lose the socket — conflating the two would lie about either
        # the connection or the agent.
        self._disconnected: bool = False
        # Set True by the ``inspect/session_ended`` handler BEFORE it
        # triggers ``mark_complete``. The reconnect loop reads this to
        # distinguish "graceful end (don't reconnect)" from "ungraceful
        # transport loss (do reconnect)". Sticky like ``_complete`` —
        # the session is genuinely over and any future EOF on this
        # transport is just plumbing teardown.
        self._session_ended_received: bool = False
        # Message ids the server has re-delivered as REPLAY (outer
        # ``inspect.replay`` marker) and we've already reset segments
        # for in the current replay pass. On reconnect → ``session/load``
        # the server replays the snapshot tail; the FIRST chunk arriving
        # for a given message_id WITH the replay marker clears that
        # group's segments so the replayed chunks rebuild cleanly
        # instead of doubling onto already-rendered text. Subsequent
        # chunks for the same message_id within the same replay just
        # append normally (id already in the set). Cleared by
        # :meth:`mark_replay_started` at the start of each new replay
        # (initial attach AND every reconnect). Works for ALL chunk
        # types — assistant content, user, system — since the marker
        # is on the outer notification, not the chunk type. Tool
        # calls / plan updates / score chips are id-keyed elsewhere
        # and idempotent — only chunked text needs this fix.
        self._replay_reset_message_ids: set[str] = set()
        # Event uuids the raw ``inspect/event`` firehose has already
        # delivered (score / span_begin / span_end). Replay re-sends
        # the same raw events, which would otherwise double score
        # chips and re-mount per-scorer indicators after the real
        # chip has replaced them. Raw events carry stable per-event
        # uuids on the wire (BaseEvent.uuid), so uuid-based dedup is
        # the simplest approach for that stream — distinct from the
        # message_id-based reset machinery for chunks above.
        # Bounded by events-per-sample which is small (handfuls per
        # sample), so we don't cap it.
        self._seen_inspect_event_uuids: set[str] = set()
        # Monotonic counter that allocates a fresh `parallel_batch_id`
        # the first time a new set of overlapping tools is tagged
        # (see :meth:`_tag_parallel_batch`). Bare counter is enough —
        # ids only need to be unique within a session, never compared
        # across sessions.
        self._next_parallel_batch_id: int = 1
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
    ) -> Literal["idle", "running", "scoring", "interrupted", "approval", "complete"]:
        """Coarse-grained turn lifecycle for the header pill.

        Six states, in priority order so a true terminal signal
        always wins over transient turn state, and an operator-blocking
        approval beats general in-flight activity:

        - ``complete``: the server-side session has ended (transport
          disconnect / explicit end). Sticky — once set, stays set.
        - ``approval``: at least one tool call is awaiting an operator
          decision via ``session/request_permission``. Prioritized
          above ``running`` because the agent is genuinely blocked on
          us — the operator needs to know they're the holdup, not just
          that "something is happening".
        - ``scoring``: the agent loop has finished and the post-agent
          scoring phase is running server-side. Latched on the outer
          ``span(name="scorers")`` boundary; only cleared by
          ``_complete`` winning above. Ranks above ``running`` and
          ``_cancelling`` because once we're scoring the user can no
          longer submit prompts (the server rejects them) and any
          in-flight residue is incidental to the scoring phase, not
          the foreground activity.
        - ``running``: at least one model event or tool call is
          currently in flight (``has_active_work``), OR a sample
          cancel is being torn down server-side (``_cancelling`` —
          set by the ^N bar; cleared implicitly when ``_complete``
          arrives and wins above), OR the last activity was within
          ``_RUNNING_QUIESCENCE_SECONDS`` (covers the sub-second gap
          between, e.g., a model event completing and the next tool
          call starting — without the tail the pill strobed on every
          micro-gap).
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
        if self._scoring_started:
            return "scoring"
        if self.has_active_work:
            return "running"
        if self._cancelling:
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
        #
        # ``_clear_active_work_signals`` finalises any in-flight
        # assistant message group (drops the spinner / dim chrome
        # without erasing content) and marks any in-flight tool
        # call as ``failed`` with an end_time so the postmortem
        # view doesn't keep showing them as still-running. Errors
        # that complete the sample without a server-side cleanup
        # would otherwise leave the spinner pinned forever.
        self._clear_active_work_signals()
        self._drop_queued_user_messages()
        # Drop any still-mounted ``scoring · X…`` indicator. The
        # indicator's normal lifecycle is begin → mount → ScoreEvent
        # replaces → unmount. If the connection drops mid-scorer (or
        # the server's ScoreEvent never reaches us for any reason),
        # the indicator gets stranded and the operator sees "scoring
        # · X…" pinned forever, even though the session pill has
        # flipped to ``complete``. Clear it on the terminal transition
        # so the postmortem view doesn't show a phantom in-progress
        # scorer.
        self._remove_scoring_indicator()
        # The session is over for good; the operator can read but not
        # drive. Implicitly we're no longer "disconnected" — the
        # disconnect flag is about the *transport* being interruptible,
        # which no longer applies. Clearing it keeps the header
        # indicator from showing an amber dot on a terminal session.
        self._disconnected = False
        self._notify()

    @property
    def disconnected(self) -> bool:
        """True while the transport is between live connections.

        Flipped True by :meth:`mark_disconnected` (receive loop saw EOF
        without a preceding ``inspect/session_ended``) and False by
        :meth:`mark_reconnected` after the reconnect loop's
        ``session/load`` succeeds. Also clears on :meth:`mark_complete`
        — once the session is terminal there's nothing to reconnect to.

        Drives the composer's send-while-disconnected guard. Orthogonal
        to :attr:`lifecycle`: the agent may still be ``running`` from
        the operator's POV during a brief transport blip.
        """
        return self._disconnected and not self._complete

    @property
    def session_ended_received(self) -> bool:
        """True iff we've processed an ``inspect/session_ended`` notification.

        Read by the reconnect loop in ``client.py`` to distinguish a
        graceful session end (don't reconnect, the sample is genuinely
        over) from an ungraceful transport loss (do reconnect, the
        sample may still be running).
        """
        return self._session_ended_received

    def mark_session_ended_received(self) -> None:
        """Note that the server signalled a clean session end.

        Sticky — subsequent calls are no-ops. Does NOT also call
        :meth:`mark_complete`; the caller handles that explicitly so
        the flag is set BEFORE the lifecycle flip (the reconnect loop
        checks the flag on disconnect, which races with the
        complete-flip-then-EOF sequence).
        """
        if not self._session_ended_received:
            self._session_ended_received = True

    def mark_disconnected(self) -> None:
        """Flag the transport as down; reconnect loop owns the cycle.

        Idempotent — subsequent calls are no-ops. Notifies subscribers
        on the first transition so the header dot flips to amber
        immediately.

        No-op once :attr:`_complete` is set: a terminal session has no
        transport to lose. Same for sessions that have received the
        clean-end notification — those are bound for ``mark_complete``
        via the existing handler and the dot would just flash before
        the lifecycle flip.
        """
        if self._complete or self._session_ended_received:
            return
        if self._disconnected:
            return
        self._disconnected = True
        self._notify()

    def mark_reconnected(self) -> None:
        """Clear the disconnected flag after the reconnect loop succeeds.

        Idempotent — subsequent calls are no-ops. Notifies subscribers
        on the True → False transition.
        """
        if not self._disconnected:
            return
        self._disconnected = False
        self._notify()

    def mark_replay_started(self) -> None:
        """Clear the per-replay message-reset tracking set.

        Called by the reconnect coordinator after each successful
        ``session/load`` (initial attach AND every reconnect) — the
        next batch of chunks arriving with the
        ``inspect.replay`` outer-meta marker will then reset their
        target message_id's segments on first sight, so doubled text
        from previously-rendered chunks is avoided. Also called on
        the initial attach where the set is already empty (no-op);
        keeping the call symmetric keeps the calling code simple.

        Synchronous + no notify: the set is internal dedup state, not
        user-visible UI.
        """
        if self._replay_reset_message_ids:
            self._replay_reset_message_ids.clear()

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

        Six things change:
        - pending message groups with no content yet are *dropped*
          entirely (the empty "assistant is thinking" bubble is just
          chrome once we know the turn was cancelled before any text
          arrived); pending groups that did stream content keep their
          text but lose ``pending=True``.
        - ``_pending_message_ids`` is cleared (drops
          :attr:`StatusState.GENERATING`).
        - in-flight tool calls are marked ``failed`` with ``end_time``
          stamped so the card stops spinning.
        - any pending approvals are resolved with
          ``cancelled=True``. Without this, an Esc during a
          pending approval would leave the client-side JSON-RPC
          handler parked on ``PendingApproval.event`` (so the
          server's request future never resolves) AND leave the
          inline section's action buttons visible on a card the
          operator just told us to abandon. Esc means "stop
          what's happening" — that includes the approval.
        - the inter-chunk quiescence timer is reset so the
          quiescence-based ``GENERATING`` branch doesn't keep firing
          until the timer expires on its own.
        - ``_interrupted`` flips to True so the lifecycle pill reads
          ``interrupted`` (instead of falling back to ``idle`` once
          ``has_active_work`` is False).
        """
        changed = self._clear_active_work_signals()
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
        # ``_interrupted`` flips to True regardless of ``changed`` so
        # the lifecycle indicator reflects the Esc even if no in-flight
        # work was actually torn down (operator pressed Esc twice, or
        # a quiescence-tail Esc that was previously gated out).
        if not self._interrupted:
            self._interrupted = True
            changed = True
        if changed:
            self._notify()

    def mark_sample_cancelling(self) -> None:
        """Optimistically clear in-flight signals after a ^N cancel-sample choice.

        Sibling to :meth:`mark_interrupted` but with two key
        differences for the cancel-sample (not cancel-turn) flow:

        - ``_interrupted`` is **not** flipped. The operator's choice
          was "wind this sample down", not "interrupt this turn" —
          flagging the lifecycle as ``interrupted`` would mis-name a
          shutdown in progress.
        - ``_cancelling`` is flipped instead, so the lifecycle pill
          keeps reading ``running`` until the server's
          ``inspect/session_ended`` arrives and flips ``_complete``
          (which wins in lifecycle resolution). Scoring and finalize
          are still running server-side during this window, so
          ``running`` is the honest description.

        Otherwise identical to :meth:`mark_interrupted`'s cleanup —
        empty pending groups are dropped, in-flight tool calls are
        stamped failed, pending approvals resolve as cancelled — so
        the visible chrome (spinning chip, ticking timers, lingering
        approve buttons) stops instantly rather than hanging until
        the cancel propagates back through the wire.
        """
        changed = self._clear_active_work_signals()
        if not self._cancelling:
            self._cancelling = True
            changed = True
        if changed:
            self._notify()

    def _clear_active_work_signals(self) -> bool:
        """Drop in-flight signals — shared core of the two cancel paths.

        Returns whether anything actually changed. Does NOT touch
        ``_interrupted`` / ``_cancelling`` / ``_last_running_at`` /
        ``_last_chunk_at`` — those are owned by the public callers
        (:meth:`mark_interrupted` and :meth:`mark_sample_cancelling`)
        because the two paths want different lifecycle dispositions
        after the cleanup.
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
        now = self._now()
        for tc in self._tool_calls_by_id.values():
            if tc.status in ("pending", "in_progress"):
                tc.status = "failed"
                if tc.end_time is None:
                    tc.end_time = now
                changed = True
        # Resolve any in-flight approvals as cancelled — same
        # rationale as ``mark_complete``. Goes through the no-notify
        # batch helper so callers can flip their lifecycle bit in the
        # SAME tick; otherwise the per-approval notify would expose
        # a transient ``lifecycle == 'idle'`` to subscribers (pending
        # cleared, lifecycle bit not yet set).
        if self._clear_pending_approvals():
            changed = True
        # Same treatment for any in-flight elicitation: drop it as
        # cancelled so the inline card disappears in lockstep with
        # the rest of the in-flight UI on interrupt / session end.
        if self._clear_pending_elicitation():
            changed = True
        # And any operator-pending cancel card — irrelevant once the
        # sample is terminating by other means; the card itself would
        # otherwise stay mounted on a session that's already complete.
        if self._clear_pending_cancel():
            changed = True
        return changed

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

        # Server stamps :data:`REPLAY_META_KEY` on every notification
        # emitted by the per-bind replay-on-attach path
        # (``Forwarders._run_replay``). The chunk handler uses it to
        # reset segments on the FIRST chunk per message_id within this
        # replay so re-streamed text doesn't double onto already-
        # rendered content (typical reconnect path). Live forwarding
        # never sets this marker. ``mark_replay_started`` clears the
        # per-replay tracking set so each new replay starts fresh.
        is_replay = bool(outer_meta.get(REPLAY_META_KEY))

        update = notification.update
        # Snapshot BEFORE applying the update so the running-tail
        # stamp also fires on the update that ENDS active work —
        # otherwise a long pending (>2s) that completes on a single
        # content/completion chunk would leave a stale stamp and the
        # lifecycle would skip the tail and fall straight to ``idle``.
        was_active = self.has_active_work
        changed = False
        if isinstance(update, (UserMessageChunk, AgentMessageChunk, AgentThoughtChunk)):
            changed = self._consume_chunk(update, is_replay=is_replay)
        elif isinstance(update, ToolCallStart):
            changed = self._consume_tool_start(update)
        elif isinstance(update, ToolCallProgress):
            changed = self._consume_tool_progress(update)
        elif isinstance(update, UsageUpdate):
            changed = self._consume_usage(update, outer_meta)
        elif isinstance(update, SessionInfoUpdate):
            changed = self._consume_session_info(update)
        elif isinstance(update, AgentPlanUpdate):
            changed = self._consume_plan_update(update)
        if changed:
            # Tag the parallel batch BEFORE notifying so subscribers
            # (notably ``TranscriptWidget._compute_defer_body``) see
            # the freshly-assigned ``parallel_batch_id`` on the same
            # refresh pass that sees the new tool state.
            self._tag_parallel_batch()
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

    def _tag_parallel_batch(self) -> None:
        """Sticky-assign a ``parallel_batch_id`` to every eligible in-progress tool.

        Whenever ≥2 tools are simultaneously eligible-in-progress
        (in_progress, not pending approval, not cancel-requested),
        every such tool gets a ``parallel_batch_id``. Tools that join
        an already-tagged group inherit that group's id; an entirely
        new overlap (no eligible tool currently carries an id)
        allocates a fresh one. Ids are sticky — never cleared — so
        they survive the tool reaching a terminal status and
        continue to scope the deferred-body reveal to its own batch.

        Eligibility mirrors :meth:`has_other_active_tools`: a tool
        awaiting operator approval doesn't count as parallel work
        (the operator is the gating actor, not another tool), and a
        cancel-requested tool is on its way out and shouldn't keep
        the batch alive.
        """
        eligible = [
            tc
            for tc in self._tool_calls_by_id.values()
            if tc.status == "in_progress"
            and tc.pending_approval is None
            and not tc.cancel_requested
        ]
        if len(eligible) < 2:
            return
        # Inherit any existing batch id present among the eligible
        # tools; otherwise allocate a new one. This keeps a tool that
        # arrives mid-batch in the same batch as its in-flight peers,
        # but starts a fresh batch when none of the current overlap
        # has been tagged yet.
        existing_id = next(
            (
                tc.parallel_batch_id
                for tc in eligible
                if tc.parallel_batch_id is not None
            ),
            None,
        )
        if existing_id is None:
            existing_id = self._next_parallel_batch_id
            self._next_parallel_batch_id += 1
        for tc in eligible:
            tc.parallel_batch_id = existing_id

    def consume_inspect_event(self, event: dict[str, Any]) -> None:
        """Route an ``inspect/event`` raw transcript payload.

        Called from the client-side ``inspect/event`` JSON-RPC route
        handler in :func:`attach_session`. Branches on the standard
        ``event`` discriminator. Routes ``"score"`` (score chip),
        ``"sample_limit"`` / ``"error"`` / ``"compaction"`` / ``"info"``
        (Inspect-native event chips), and ``"span_begin"`` /
        ``"span_end"`` (scoring-phase boundary + per-scorer indicator
        lifecycle).

        Replay-dedup: each event carries a stable ``uuid`` from
        ``BaseEvent``. On reconnect the server replays the snapshot
        which re-fires the same raw events, which would otherwise
        double chips and re-mount per-scorer indicators after the
        real chip has already replaced them. The first occurrence of
        a uuid is processed normally and recorded; subsequent
        deliveries of the same uuid drop silently.
        """
        uuid = event.get("uuid")
        if isinstance(uuid, str) and uuid:
            if uuid in self._seen_inspect_event_uuids:
                return
            self._seen_inspect_event_uuids.add(uuid)
        kind = event.get("event")
        if kind == "score":
            self.consume_score_event(event)
        elif kind == "sample_limit":
            self.consume_sample_limit_event(event)
        elif kind == "error":
            self.consume_error_event(event)
        elif kind == "compaction":
            self.consume_compaction_event(event)
        elif kind == "info":
            self.consume_info_event(event)
        elif kind == "span_begin":
            self._consume_span_begin(event)
        elif kind == "span_end":
            self._consume_span_end(event)

    def _consume_span_begin(self, event: dict[str, Any]) -> None:
        """Filter ``span_begin`` events to scoring-phase boundaries.

        Two scoring spans matter to the operator:

        1. The outer ``span(name="scorers")`` — opens once when the
           scoring phase begins. We use it to clear the plan strip:
           the agent loop has finished, so a still-mounted plan would
           mislead the operator into thinking work was still in
           progress. Clearing on the scoring boundary keeps the plan
           visible right up until scoring starts.
        2. The inner ``span(name=<scorer>, type="scorer")`` — opens
           per scorer in turn. We use it to mount a ``scoring · X…``
           indicator chip; the next ``ScoreEvent`` replaces it. If
           scoring errors before a score lands, the indicator persists
           as the last-recorded "what was running" signal — exactly
           what the operator needs.

        Disambiguation: ``span(name="scorers")`` is opened without a
        ``type`` argument, but :func:`util._span.span` defaults
        ``type`` to ``name`` when omitted — so the wire payload
        carries ``type="scorers"`` (not ``None``). The inner spans
        carry ``type="scorer"`` (singular). The check uses the
        singular/plural distinction to tell them apart.

        The wire firehose forwards every span begin (agent / tool /
        sub-agent / framework / etc.); everything outside the two
        cases above is silently dropped.
        """
        name = event.get("name")
        span_type = event.get("type")
        # Outer scoring boundary — agent loop is done. Drop the plan
        # strip; leaving it up reads as "still working on it" even
        # though we've moved on to the post-agent scoring phase.
        # ``_scoring_started`` latches so any later replayed
        # ``AgentPlanUpdate`` (semantic replay can arrive AFTER raw
        # replay on late-attach) is suppressed by
        # ``_consume_plan_update`` rather than resurrecting the plan.
        if name == SCORERS_SPAN_NAME and span_type == SCORERS_SPAN_NAME:
            changed = not self._scoring_started
            self._scoring_started = True
            if self.plan_entries is not None:
                self.plan_entries = None
                changed = True
            if changed:
                self._notify()
            return
        # Per-scorer indicator.
        if span_type != SCORER_SPAN_TYPE:
            return
        if not isinstance(name, str) or not name:
            return
        # Defensive — drop any prior indicator that the previous
        # ScoreEvent / span_end didn't clear. The new scorer's
        # indicator takes its place.
        self._remove_scoring_indicator()
        self._score_chip_counter += 1
        span_id = event.get("id")
        chip = ScoreChip(
            scorer=None,
            value="",
            passed=None,
            reason=f"scoring · {name}…",
            chip_id=f"score-{self._score_chip_counter}",
            span_id=span_id if isinstance(span_id, str) else None,
            started_at=self._now(),
            scorer_name=name,
        )
        self.items.append(chip)
        self._scoring_indicator = chip
        self._notify()

    def _consume_span_end(self, event: dict[str, Any]) -> None:
        """Clear the per-scorer indicator when its span closes.

        Covers the cases where the scorer span ended without firing a
        ``ScoreEvent`` — most commonly because the scorer returned
        ``None`` (legitimate; some scorers opt out per-sample) or
        raised. Without this, the indicator would persist past the
        scorer's actual lifetime, telling the operator "scoring · X…"
        is still running when X has already moved on. Only the
        matching span id clears — unrelated span_ends (agent / tool /
        outer scorers boundary) are ignored.
        """
        if self._scoring_indicator is None:
            return
        if event.get("id") != self._scoring_indicator.span_id:
            return
        self._remove_scoring_indicator()
        self._notify()

    def _remove_scoring_indicator(self) -> None:
        """Drop the currently-mounted ``scoring · X…`` indicator, if any.

        Identified by tracked reference so we never miss-remove a
        sibling chip with a similar reason. No-op when no indicator is
        live (the normal "between samples" / "no scoring yet" state).
        Caller is responsible for the surrounding ``_notify()`` —
        :meth:`consume_score_event` batches removal + mount into one
        update.
        """
        if self._scoring_indicator is None:
            return
        try:
            self.items.remove(self._scoring_indicator)
        except ValueError:
            # Already evicted by the turn-cap, or never made it into
            # items for some reason. Either way the slot is gone.
            pass
        self._scoring_indicator = None

    def consume_score_event(self, event: dict[str, Any]) -> None:
        """Mount an inline ScoreChip from a serialized ``ScoreEvent``.

        Inserts a new chip at the current end of :attr:`items`. No
        separate accumulator: chips rotate with the existing
        ``_MAX_ASSISTANT_TURNS`` conversation window (chips anchored
        before the surviving message-group window are evicted in the
        same sweep — see :meth:`_enforce_turn_cap`).

        Score payload shape mirrors ``inspect_ai.event.ScoreEvent``
        serialized to JSON via Pydantic: ``score.value`` is a scalar or
        list/dict; ``scorer`` is the scorer name; ``score.explanation``
        carries the reason. The chip extracts a display-friendly
        triple ``(scorer, value, passed, reason)`` — ``passed`` is
        ``True`` only when :func:`_classify_score_value` decides the
        score is an unambiguous pass (``value_to_float`` == 1.0);
        partial credit, explicit zero, and non-scalar shapes all
        render as a neutral chip rather than a failure verdict.

        If a ``scoring…`` indicator chip is currently mounted (from a
        prior ``span_begin(name="scorers")``), it's removed in the
        same tick — the real score chip supersedes the placeholder so
        a fast scorer doesn't leave a redundant breadcrumb above its
        own result. The indicator only persists during the gap
        between scoring-phase-begin and the first actual score.
        """
        score = event.get("score") or {}
        raw_value = score.get("value")
        value_str = _format_score_value(raw_value)
        # ``_classify_score_value`` flags only unambiguous passes
        # (``value_to_float`` == 1.0). Anything else — partial credit,
        # explicit zero, non-binary shapes — collapses to ``None`` so
        # the widget renders a neutral chip rather than asserting a
        # failure verdict the score's value doesn't actually prove.
        passed = _classify_score_value(raw_value)
        scorer = event.get("scorer")
        if not isinstance(scorer, str) or not scorer:
            scorer = None
        reason = score.get("explanation")
        if not isinstance(reason, str) or not reason:
            reason = None
        answer = score.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            answer = None
        # Replace the live "scoring · <scorer>…" indicator (if any) —
        # the real score chip is the better signal now that it's
        # arrived. The next per-scorer ``span_begin`` will mount a
        # fresh indicator for the next scorer.
        self._remove_scoring_indicator()
        self._score_chip_counter += 1
        chip = ScoreChip(
            scorer=scorer,
            value=value_str,
            passed=passed,
            reason=reason,
            chip_id=f"score-{self._score_chip_counter}",
            answer=answer,
        )
        self.items.append(chip)
        self._notify()

    # ------------------------------------------------------------------
    # Inspect-native event chips (sample_limit / error / compaction / info)
    # ------------------------------------------------------------------

    def consume_sample_limit_event(self, event: dict[str, Any]) -> None:
        """Mount an inline event chip for a serialized ``SampleLimitEvent``.

        Wire shape mirrors :class:`inspect_ai.event.SampleLimitEvent`:
        a ``type`` discriminator (``message`` / ``time`` / ``working``
        / ``token`` / ``cost`` / ``operator`` / ``custom``) plus a
        human-readable ``message`` and an optional numeric ``limit``.

        The chip surfaces all three: the type and the numeric limit
        in the header (``limit · token · 100.0k``), and the message
        in the body. Sample-limit events are terminal — the message
        is the operator's only inline explanation of why the run
        stopped, so dropping it would force a transcript dive for
        what's a one-line answer.
        """
        limit_type = event.get("type")
        limit_value = event.get("limit")
        header_parts = ["limit"]
        if isinstance(limit_type, str) and limit_type:
            header_parts.append(limit_type)
        if isinstance(limit_value, (int, float)):
            header_parts.append(_format_limit_value(limit_type, float(limit_value)))
        header = " · ".join(header_parts)
        message = event.get("message")
        body: str | None = None
        if isinstance(message, str):
            stripped = message.strip()
            body = stripped if stripped else None
        self._append_event_chip(kind="sample_limit", header=header, body=body)

    def consume_error_event(self, event: dict[str, Any]) -> None:
        """Mount an inline event chip for a serialized ``ErrorEvent``.

        Wire shape mirrors :class:`inspect_ai.event.ErrorEvent`: an
        ``error`` payload (``EvalError``) carrying ``message`` and
        ``traceback`` fields. The chip header stays bare (``error``);
        the message renders on the body row below so the operator can
        scan it without it being truncated by the chip-row width and
        without losing the full multi-line message. Traceback rides
        :attr:`EventChip.traceback` so the widget can give it a
        click-to-expand affordance modelled on ``_ReasoningBlock``.
        """
        error = event.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        if not isinstance(message, str):
            message = None
        # Header is just ``error`` — the message is wider than the
        # chip row in practice (exception class + tail), and inlining
        # the first line meant the operator either lost the rest mid-
        # truncation or had to expand the body to see what mattered.
        # Promoting the full message to the body row keeps the chip
        # scannable and the message readable.
        body = message if message and message.strip() else None
        # Prefer ``traceback_ansi`` (the Rich-rendered ``Traceback``
        # exported to ANSI escape codes by ``format_traceback`` →
        # ``rich_traceback``) over the plain ``traceback`` field —
        # the ANSI version carries frame summaries, source-line
        # context, and syntax colouring already laid out, so the
        # widget can render it via ``Text.from_ansi`` and inherit
        # the chip's tinted background. Fall back to the plain
        # field when ANSI is missing or empty (truncated tracebacks
        # also populate ANSI with the plain text upstream, so the
        # fallback is rare in practice).
        traceback_ansi = (
            error.get("traceback_ansi") if isinstance(error, dict) else None
        )
        traceback_plain = error.get("traceback") if isinstance(error, dict) else None
        if isinstance(traceback_ansi, str) and traceback_ansi.strip():
            traceback = traceback_ansi
        elif isinstance(traceback_plain, str) and traceback_plain.strip():
            traceback = traceback_plain
        else:
            traceback = None
        self._append_event_chip(
            kind="error",
            header="error",
            body=body,
            traceback=traceback,
            body_format="plain",
        )

    def consume_compaction_event(self, event: dict[str, Any]) -> None:
        """Mount an inline event chip for a serialized ``CompactionEvent``.

        Wire shape mirrors :class:`inspect_ai.event.CompactionEvent`:
        a ``type`` discriminator (``summary`` / ``edit`` / ``trim``),
        optional ``tokens_before`` / ``tokens_after`` counts, and an
        optional ``source``. The chip renders as a single line — the
        strategy + the token delta — with no body row; the ``source``
        field is metadata about *who* ran the compaction, which the
        operator rarely needs at a glance, and a multi-row body for
        a transient compaction chip was more visual weight than the
        event warranted.
        """
        compaction_type = event.get("type")
        parts: list[str] = ["compaction"]
        if isinstance(compaction_type, str) and compaction_type:
            parts.append(compaction_type)
        before = event.get("tokens_before")
        after = event.get("tokens_after")
        if isinstance(before, int) and isinstance(after, int):
            parts.append(
                f"tokens {_format_token_count(before)} → {_format_token_count(after)}"
            )
        header = " · ".join(parts)
        self._append_event_chip(kind="compaction", header=header, body=None)

    def consume_info_event(self, event: dict[str, Any]) -> None:
        """Mount an inline event chip for a serialized ``InfoEvent``.

        Wire shape mirrors :class:`inspect_ai.event.InfoEvent`: an
        optional ``source`` plus a ``data`` payload that can be any
        JSON value. Header surfaces ``source`` when present (subsystem
        diagnostics typically tag themselves). Body renders as
        markdown when ``data`` is a string, or as syntax-highlighted
        JSON (via :class:`rich.json.JSON`) when it's a structured
        shape — the JSON path skips the markdown fenced-code-block
        background so structured payloads sit on the chip's own
        manila card band.
        """
        source = event.get("source")
        header = "info"
        if isinstance(source, str) and source.strip():
            header = f"info · {source.strip()}"
        data = event.get("data")
        body, body_format = _format_info_data(data)
        self._append_event_chip(
            kind="info", header=header, body=body, body_format=body_format
        )

    def _append_event_chip(
        self,
        *,
        kind: EventChipKind,
        header: str,
        body: str | None,
        traceback: str | None = None,
        body_format: Literal["markdown", "json", "plain"] = "markdown",
    ) -> None:
        """Mint an :class:`EventChip`, append to items, and notify subscribers."""
        self._event_chip_counter += 1
        chip = EventChip(
            kind=kind,
            header_summary=header,
            body_text=body,
            chip_id=f"event-{self._event_chip_counter}",
            traceback=traceback,
            body_format=body_format,
        )
        self.items.append(chip)
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

    # ------------------------------------------------------------------
    # Elicitation handshake (parallel to the approval pair above)
    # ------------------------------------------------------------------

    def consume_elicitation_request(self, pending: PendingElicitation) -> None:
        """Park a ``PendingElicitation`` so the inline card mounts.

        The caller (the client-side ``elicitation/create`` handler in
        ``client.py``) owns the ``PendingElicitation`` and reads its
        ``action`` / ``content`` AFTER awaiting ``pending.event``. By
        passing the object in (rather than letting state synthesize
        it) the handler keeps the same reference that
        :meth:`resolve_elicitation` mutates — single source of truth
        for the resolution outcome.

        Idempotence: an existing pending elicitation is cancelled
        first so a misbehaving / racing client can't strand the prior
        request. In practice the agent loop only issues one
        ``ask_user`` at a time, so this is defence-in-depth.
        """
        if self.pending_elicitation is not None:
            self._resolve_elicitation_inner(action="cancel")
        self.pending_elicitation = pending
        self._notify()

    def resolve_elicitation(
        self,
        *,
        action: ElicitationAction,
        content: dict[str, Any] | None = None,
    ) -> None:
        """Resolve the pending elicitation; fires the event so the handler returns.

        Idempotent: re-resolving an already-resolved elicitation (or
        resolving when there's none pending) is a no-op. Pass
        ``action="accept"`` with ``content`` for an operator submission,
        ``action="decline"`` for an operator-driven decline, or
        ``action="cancel"`` for unmount / disconnect / Esc / session
        completion. The handler reads the slots set here to build its
        wire response.
        """
        if self._resolve_elicitation_inner(action=action, content=content):
            self._notify()

    def _resolve_elicitation_inner(
        self,
        *,
        action: ElicitationAction,
        content: dict[str, Any] | None = None,
    ) -> bool:
        """Mutate-only resolve. Returns True if anything changed.

        Used by :meth:`resolve_elicitation` (which notifies after) and
        by bulk-transition helpers like
        :meth:`_clear_pending_elicitation` that batch the elicitation
        cancel alongside other mutations into a single ``_notify()``.

        Fires ``pending.event`` here so the parked JSON-RPC handler
        wakes immediately — the wire response is unrelated to the
        UI-refresh notification.
        """
        pending = self.pending_elicitation
        if pending is None:
            return False
        pending.action = action
        pending.content = content if action == "accept" else None
        self.pending_elicitation = None
        pending.event.set()
        return True

    def _clear_pending_elicitation(self) -> bool:
        """Resolve any in-flight elicitation as cancelled, NO notify.

        Returns True if anything cleared. Mirrors
        :meth:`_clear_pending_approvals` — used by the bulk
        cancellation paths (``mark_complete`` /
        ``mark_interrupted`` / ``mark_sample_cancelling`` via
        ``_clear_active_work_signals``) so the elicitation card
        disappears in lockstep with the rest of the in-flight UI
        and the handler unblocks to send a ``cancel`` response.
        """
        return self._resolve_elicitation_inner(action="cancel")

    # ------------------------------------------------------------------
    # Cancel-sample handshake (operator-driven; no parked handler)
    # ------------------------------------------------------------------

    def consume_cancel_request(self, pending: PendingCancel) -> None:
        """Park a :class:`PendingCancel` so the inline cancel card mounts.

        Idempotent: if a cancel is already pending, this is a no-op —
        the operator pressing ``^N`` while the card is already up
        does not stomp the existing pending. (The session screen
        treats a repeat ``^N`` as a "scroll back to the card + re-
        engage auto-follow" gesture; see Phase 6b plan.)

        Unlike the elicitation / approval pairs, there's no parked
        JSON-RPC handler waiting on an event — the cancel-sample
        flow is fire-and-forget from the operator's perspective and
        the card itself fires the wire RPC when Score / Error is
        picked.
        """
        if self.pending_cancel is None:
            self.pending_cancel = pending
            self._notify()

    def resolve_cancel(self) -> None:
        """Clear ``pending_cancel`` and notify subscribers.

        Called by the card after the operator picks Back (no RPC) or
        after the ``inspect/cancel_sample`` RPC has been dispatched
        (success or failure). The screen's apply-loop sees the
        cleared slot and unmounts the card. Also clears the screen's
        auto-follow flag (managed in :class:`SessionScreen`).

        Idempotent.
        """
        if self.pending_cancel is not None:
            self.pending_cancel = None
            self._notify()

    def _clear_pending_cancel(self) -> bool:
        """Clear any pending cancel, NO notify.

        Returns True if anything cleared. Used by bulk-transition
        helpers (``mark_complete`` / ``mark_interrupted``) so the
        cancel card disappears in lockstep with the rest of the
        in-flight UI when the sample terminates by other means.
        """
        if self.pending_cancel is None:
            return False
        self.pending_cancel = None
        return True

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
        *,
        is_replay: bool = False,
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

        # Replay-reset: when the server is replaying a snapshot
        # (``inspect.replay`` marker on the outer notification), the
        # FIRST chunk per message_id within this replay clears the
        # group's segments so the replayed chunks rebuild from
        # scratch instead of doubling onto already-rendered text.
        # Subsequent chunks for the same message_id within the same
        # replay just append normally (id already in
        # ``_replay_reset_message_ids``); the set is cleared at the
        # start of each replay by ``mark_replay_started``.
        #
        # Works for ALL chunk types (assistant content + reasoning,
        # user, system) — the marker is on the outer notification,
        # not the chunk type. Important: the server doesn't emit a
        # completion marker for content-producing assistant
        # messages (those clear pending implicitly on first content
        # chunk), so a heuristic based on the completion marker
        # would miss the common case; the explicit replay marker
        # covers it deterministically.
        existing = self._messages_by_id.get(message_id)
        if (
            is_replay
            and existing is not None
            and message_id not in self._replay_reset_message_ids
        ):
            existing.segments.clear()
            self._replay_reset_message_ids.add(message_id)

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
        meta = getattr(update, "field_meta", None) or {}
        tc = ToolCallState(
            tool_call_id=update.tool_call_id,
            title=update.title,
            kind=update.kind,
            status=status,
            content=list(update.content) if update.content is not None else None,
            raw_input=update.raw_input,
            raw_output=update.raw_output,
            start_time=start_time,
            cancelable=bool(meta.get(TOOL_CALL_CANCELABLE_META_KEY, True)),
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

    def _consume_usage(self, update: UsageUpdate, outer_meta: dict[str, Any]) -> bool:
        # ``totalMessages`` rides on the outer ``field_meta`` (the inspect-
        # ext extension lane) since ACP's ``UsageUpdate`` schema has no
        # first-class message-count field. Server stamps it in
        # ``event_mapping._map_model_event``; absent key falls back to 0
        # so older servers (or paths that don't bind to an ActiveSample)
        # render the ``messages`` chip as em-dash via ``format_tokens(0)``.
        messages = int(outer_meta.get(TOTAL_MESSAGES_META_KEY) or 0)
        self.usage = UsageState(used=update.used, size=update.size, messages=messages)
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
            # ScoreChip / EventChip have no side-state to clean up
            # beyond removal from ``items`` — they live only here
            # (no ``_*_by_id`` index, no pending sets to discard).
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
        # Suppress plan updates that arrive AFTER the scoring boundary
        # has fired. Concretely this is the late-attach replay race:
        # the raw-event firehose replays its events first (clearing
        # the plan via ``span_begin(name="scorers")``) and the
        # semantic firehose replays after that (which would otherwise
        # re-mount the historical AgentPlanUpdate that was live
        # mid-agent — the operator would see the plan resurrect after
        # scoring had already finished). Once scoring has started,
        # any plan update is stale.
        if self._scoring_started:
            return False
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
    def cancel_tool_call_ids(self) -> list[str]:
        """All eligible in-flight tool ids that a ``^L`` press should cancel.

        Eligibility (same as :attr:`cancel_tool_call_id`): in-flight
        (``pending`` / ``in_progress``), not awaiting an operator
        approval decision (the approval bar's ``reject`` /
        ``terminate`` is the right exit there), not already
        cancel-requested (so a second ``^L`` is a no-op on tools the
        operator has already cancelled), and ``cancelable`` (bridged
        agents' tool calls have no pending ``ToolEvent`` to cancel, so
        they're excluded — a ``^L`` there would no-op).

        Under parallel tool calls multiple tools share the in-flight
        state; a single ``^L`` press fans out to cancel all of them
        rather than dispatching one at a time. Order is
        ``start_time`` ascending so the on-screen cancelling-state
        transitions show oldest-first; semantically any order is
        correct because each fires an independent RPC.
        """
        eligible = [
            tc
            for tc in self._tool_calls_by_id.values()
            if tc.status in ("pending", "in_progress")
            and tc.pending_approval is None
            and not tc.cancel_requested
            and tc.cancelable
        ]
        eligible.sort(key=lambda tc: tc.start_time)
        return [tc.tool_call_id for tc in eligible]

    @property
    def cancel_tool_call_id(self) -> str | None:
        """First id from :attr:`cancel_tool_call_ids`, or ``None``.

        Used by :class:`SessionScreen.check_action` to decide whether
        the screen-footer ``cancel tool`` hint should be visible.
        """
        ids = self.cancel_tool_call_ids
        return ids[0] if ids else None

    def has_other_active_tools(self, exclude_tool_call_id: str) -> bool:
        """True if any tool other than ``exclude_tool_call_id`` is actively running.

        Mirrors the eligibility predicate used by
        :attr:`cancel_tool_call_ids` but excludes one specific tool
        (the caller, asking "is anyone else still running?"). Used by
        :class:`TranscriptWidget` to decide whether a completed
        ``ToolCallWidget`` should reveal its body or hold for siblings:
        under parallel tool calls, streaming completed results in
        while peers are still running pulls the eye away from the
        cards the operator is actively tracking.

        Pending-approval tools are excluded because the operator may
        need to see siblings' results to inform the approval decision.
        Cancel-requested tools are excluded because the operator has
        already chosen an exit for that tool; results shouldn't be
        gated waiting on the cancel to land.
        """
        return any(
            tc.tool_call_id != exclude_tool_call_id
            and tc.status == "in_progress"
            and tc.pending_approval is None
            and not tc.cancel_requested
            for tc in self._tool_calls_by_id.values()
        )

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
