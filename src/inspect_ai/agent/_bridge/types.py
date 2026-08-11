from enum import IntEnum
from functools import lru_cache
from typing import TYPE_CHECKING, NamedTuple, NoReturn, Sequence, Set

from shortuuid import uuid

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent._agent import AgentState
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._compaction import (
    Compact,
    CompactionStrategy,
)
from inspect_ai.model._compaction import (
    compaction as create_compaction,
)
from inspect_ai.model._model import GenerateFilter, Model, ModelEventSink
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._checkpoint.checkpointer import Checkpointer
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer

if TYPE_CHECKING:
    # deferred: `_bridge.types` is imported at the top of `inspect_ai.agent`, well
    # before `inspect_ai.approval` can be initialized (approval -> event -> scorer
    # cycles back through partially-initialized modules). Same reason
    # `model/_call_tools.py` defers it.
    from inspect_ai.approval._policy import ApprovalPolicy


class AgentBridge:
    """Agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None = None,
        retry_refusals: int | None = None,
        compaction: CompactionStrategy | None = None,
        model: str | None = None,
        model_aliases: dict[str, str | Model] | None = None,
        model_event_sink: ModelEventSink | None = None,
        forward_generation_config: bool = False,
        approval: list["ApprovalPolicy"] | None = None,
        checkpointer: Checkpointer | None = None,
        allow_remote_mcp: bool = True,
        allow_remote_media: bool = True,
    ) -> None:
        # Capabilities a client-declared request may reach for. Both default to
        # permissive because an in-process scaffold already shares the host's
        # network and filesystem; `sandbox_agent_bridge()` tightens them, since
        # there the sandbox boundary is the thing being defended.
        self.allow_remote_mcp = allow_remote_mcp
        self.allow_remote_media = allow_remote_media
        self._cp = checkpointer or _NoopCheckpointer()
        # AgentState is not a BaseModel so it can't be tracked directly;
        # track its messages and output separately (same approach as react()).
        #
        # Register them for backup unconditionally, but only adopt the restored
        # value when resuming purely to re-score. On a normal "resume" the
        # sandbox agent rebuilds its own conversation (e.g. claude_code's
        # --resume replays the full history back through the bridge), so
        # _track_state repopulates state live; overwriting state here would feed
        # the scaffold a restored, mid-turn (assistant-terminated) conversation,
        # which is wrong for continuation and breaks prompt builders that require
        # a non-assistant final message. "resume_for_scoring" skips the agent
        # loop, so the tracked snapshot is the only source of the final state.
        restored_messages = self._cp.track(
            "bridge_messages",
            lambda: self.state.messages,
            state.messages,
            value_type=list[ChatMessage],
        )
        restored_output = self._cp.track(
            "bridge_output", lambda: self.state.output, state.output
        )
        if self._cp.attempt == "resume_for_scoring":
            state.messages = restored_messages
            state.output = restored_output
        self.state = state
        self._message_ids = self._cp.track(
            "bridge_message_ids",
            lambda: self._message_ids,
            {},
            value_type=dict[str, list[str]],
        )
        self._compaction_prefix = self._cp.track(
            "bridge_compaction_prefix",
            lambda: self._compaction_prefix,
            state.messages.copy(),
            value_type=list[ChatMessage],
        )
        self.filter = filter
        self.retry_refusals = retry_refusals
        self.model = model
        self.model_aliases: dict[str, str | Model] = model_aliases or {}
        self.model_event_sink = model_event_sink
        self.forward_generation_config = forward_generation_config
        self.approval = approval
        self._compaction = compaction
        self._compact: Compact | None = None
        self._last_message_count = 0
        # thread-tracking state for _track_state (see its docstring). the
        # descent anchor is the initial input (via _compaction_prefix, which
        # restores to the original input on checkpoint resume).
        initial_messages = [m for m in self._compaction_prefix if m.role != "system"]
        self._initial_fps = [_message_fingerprint(m) for m in initial_messages]
        self._initial_fps_condensed = [
            _condensed_fingerprint(fp) for fp in self._initial_fps
        ]
        self._initial_texts = [m.text.strip() for m in initial_messages]
        self._tracked_fps: list[_MessageFingerprint] | None = None
        self._tracked_calls = 0
        self._tracked_descends: _Descent | None = None
        self._candidate_fps: list[_MessageFingerprint] | None = None
        self._pending_operator = 0
        self._operator_keys: set[str] = set()

    state: AgentState
    """State updated from messages traveling over the bridge."""

    filter: GenerateFilter | None
    """Filter for bridge model generation.

    A filter may substitute for the default model generation by returning a ModelOutput or return None to allow default processing to continue.
    """

    model: str | None
    """Fallback model for requests that don't use ``inspect`` or ``inspect/``
    prefixed names.  ``None`` means no fallback (the request model name is
    used as-is).
    """

    model_aliases: dict[str, str | Model]
    """Map of model name aliases.  When a request uses a name that appears
    here, the corresponding value (a ``Model`` instance or model spec string)
    is used instead.  Checked before the fallback ``model``.
    """

    model_event_sink: ModelEventSink | None
    """Optional sink that takes ownership of `ModelEvent` emission for calls
    routed through the bridge. When set, the bridge installs it around
    `model.generate()`; `_record_model_interaction` then dispatches pending /
    complete events to the sink instead of emitting them to the transcript.
    Use this to attribute bridge model events to externally-managed agent
    spans (e.g. spans driven by a side-channel event stream).
    """

    forward_generation_config: bool
    """Whether to forward client generation parameters to the model.

    When `False` (the default), generation-tuning parameters from the incoming
    request (e.g. `max_tokens`, `temperature`, `top_p`/`top_k`, reasoning effort /
    thinking budget, penalties, `n`, logprobs) are dropped; the resolved Inspect
    model config and provider defaults govern generation. This prevents a scaffold
    from imposing parameters it computed for a different model than the one actually
    serving the request. Structural parameters (system prompt, tools, tool choice,
    response format, stop sequences) are always forwarded. Set `True` to forward
    the client's generation parameters (faithful-proxy behavior).
    """

    approval: list["ApprovalPolicy"] | None
    """Approval policies for tool calls made by the bridged agent.

    Applied to the tool calls in each bridged model response, replacing any ambient
    policies for the duration of the approval. Ambient policies (eval-level and
    task-level) already apply without this; it exists because a sandbox bridge's
    generations run in the sandbox service task, which holds a *copy* of the context
    taken when the bridge was entered — so an `approval()` block entered inside the
    agent body is invisible to them. Setting policies here is the only reliable way
    to scope approval from within the agent.
    """

    def request_terminate(self, reason: str) -> NoReturn:
        """Terminate the sample from a bridged generation.

        Raises `TerminateSampleError`, which propagates out through the agent to the
        sample runner. `SandboxAgentBridge` overrides this: its generations run in
        the sandbox service task, where exceptions become RPC error responses instead
        of propagating.
        """
        raise TerminateSampleError(reason)

    def compaction(
        self, tools: Sequence[ToolInfo | Tool], model: Model
    ) -> Compact | None:
        """Compaction function for bridge.

        Note: This will always return the same compaction function for a
        given instance of the bridge.

        Args:
            tools: Tool definitions (included in token count as they consume context).
            model: Target model for compacted input.
        """
        if self._compact is None and self._compaction is not None:
            self._compact = create_compaction(
                self._compaction,
                prefix=self._compaction_prefix,
                tools=tools,
                model=model,
                checkpointer=self._cp,
            )
        return self._compact

    def note_operator_message(self, message: ChatMessageUser) -> None:
        """Record that an operator-injected user message is entering the agent.

        Called by a bridged scaffold (e.g. inspect_swe, issue #66) right after it
        drains an operator message from the agent channel and forwards it to its
        underlying CLI. A bridged scaffold round-trips the message through its own
        conversation store, so it re-enters ``bridge_generate`` as a plain
        ``ChatMessageUser`` with ``source=None`` (the provenance the ACP transport
        stamped at submit time is lost). The bridge restores ``source="operator"``
        inside ``bridge_generate`` so it renders distinctly in the ACP TUI and
        persists into the eval log (model events + final messages).

        Recognition is positional — the operator turn is the latest user message
        in the next request (queued sends coalesce into one) — so only the pending
        count is used here; the ``message`` argument is accepted for caller clarity.
        """
        self._pending_operator += 1

    def _id_for_message(
        self, message: ChatMessage, conversation: list[ChatMessage]
    ) -> str:
        # message_id we will return
        message_id: str | None = None

        # turn message into a hash so it can be a dictionary key
        message_key = message_json_hash(to_json_str_safe(message))

        # do we already have an id for this message that isn't in the conversation?
        conversation_ids: Set[str] = {m.id for m in conversation if m.id is not None}
        message_ids = self._message_ids.get(message_key, [])
        for id in message_ids:
            if id not in conversation_ids:
                message_id = id
                break

        # if we didn't find an id then generate a new one and update our record
        if message_id is None:
            message_id = uuid()
            message_ids.append(message_id)
            self._message_ids[message_key] = message_ids

        # return the id
        return message_id

    _message_ids: dict[str, list[str]]

    async def _track_state(self, input: list[ChatMessage], output: ModelOutput) -> None:
        """Track agent state by observing generations made through the bridge.

        We need to distinguish the "main" thread of generation from side /
        sub-agent model calls (e.g. claude code does bash path detection with a
        side call; opencode names the session with a title-generation call).
        Message counts alone can't do this: a side call that is longer than the
        main conversation (opencode's title call fires before the main loop's
        first call and carries an extra preamble message) would permanently
        displace the real conversation. Instead we track thread identity:

        - A call whose messages extend the tracked thread (the tracked messages
          are a prefix of it, compared by role + text) always updates the state.
        - Otherwise the call starts a new thread and we consult *descent*: a
          thread descends from the initial input if its non-system messages
          start with the initial input's non-system messages (verbatim, as
          their condensed ``attachment://<hash>`` references, or as decorated
          text containing the initial message — see `_descends_from_initial`).
          Descent is graded (see `_Descent`): quote-wrapped store-transform
          anchors outrank verbatim/condensed anchors, which outrank generic
          containment, which outranks no anchor. A stronger-descending
          thread displaces the tracked thread when that thread is a one-shot
          call (the opencode title case) or when the stronger call is longer
          than the tracked thread (the main loop reclaiming tracking from a
          promoted sub-agent loop, below). The grading means a side call that
          quotes the whole prompt inside a preamble message (containment
          grade) can never outrank a verbatim-anchored main loop, and a side
          call resending the raw prompt verbatim (a topic detector) can never
          outrank opencode's quote-wrapped main loop — while a decorated main
          loop still displaces a non-descending title call. A
          weaker-descending call never directly displaces the tracked thread
          (side calls, sub-agent loops).
        - When descent can't discriminate (equal verdicts, or no initial input
          to anchor on — e.g. a scaffold that rewrites the input prompt), fall
          back to the legacy length heuristic: adopt the new thread when it
          has more messages than the previous generation (or, when both
          threads descend, than the tracked thread — so a parked side call
          can't lower the bar for a stray descending one-shot).
        - A new thread that isn't adopted is remembered as a candidate; if the
          next call extends it, it's a live agent loop and is promoted. This is
          what recovers tracking after history compaction (scaffold-side
          compaction replaces the conversation with a summary, so the
          post-compaction loop neither extends the tracked thread nor descends
          from the initial input). Promotion is unconditional, so a multi-call
          sub-agent loop transiently takes over tracking this way — the main
          loop reclaims it on resumption, by extension when it makes several
          further calls (candidate promotion) or by the longer-descending-call
          displacement above when it makes only one.
        """
        messages = input + [output.message]
        fps = [_message_fingerprint(m) for m in messages]

        if self._tracked_fps is None:
            # first observed call: best information available so far (if it is
            # a side call the rules below displace it later)
            self._adopt_thread(messages, output, fps, calls=1)
        elif _extends(self._tracked_fps, fps):
            self._adopt_thread(messages, output, fps, calls=self._tracked_calls + 1)
        elif self._candidate_fps is not None and _extends(self._candidate_fps, fps):
            # the candidate got continued so it is a live agent loop (e.g. the
            # post-compaction conversation): promote it over the tracked thread
            self._adopt_thread(messages, output, fps, calls=2)
        else:
            descends = self._descends_from_initial(messages, fps)
            if (
                descends is not None
                and self._tracked_descends is not None
                and descends > self._tracked_descends
                and (self._tracked_calls == 1 or len(messages) > len(self._tracked_fps))
            ):
                # the real conversation displacing a weaker-anchored thread:
                # a one-shot side call that landed first (the opencode title
                # case) or, when longer than the tracked thread, a promoted
                # multi-call sub-agent loop (a main loop resuming with a
                # single final call would otherwise be parked as a candidate
                # that nothing extends). a short stray descending one-shot
                # still can't displace an established weaker-anchored thread
                # (flapping guard).
                self._adopt_thread(messages, output, fps, calls=1)
            elif descends == self._tracked_descends and len(messages) > (
                len(self._tracked_fps) if descends else self._last_message_count
            ):
                # legacy length heuristic. when both threads descend, compare
                # against the tracked thread so a parked side call can't lower
                # the bar for a stray descending one-shot; for False/None
                # verdicts keep the previous-call comparison — a scaffold that
                # rewrites message text every call (breaking fingerprint
                # continuity and descent) recovers from compaction only
                # through it.
                self._adopt_thread(messages, output, fps, calls=1)
            else:
                self._candidate_fps = fps

        self._last_message_count = len(messages)

        # tick the checkpointer
        await self._cp.tick()

    def _adopt_thread(
        self,
        messages: list[ChatMessage],
        output: ModelOutput,
        fps: list["_MessageFingerprint"],
        calls: int,
    ) -> None:
        """Make `messages` the tracked main thread (see `_track_state`).

        `calls` is the number of bridge calls attributed to the thread; a
        stronger-descending thread may displace a weaker-anchored one-shot
        (`calls == 1`) thread regardless of length.
        """
        self.state.messages = messages
        self.state.output = output
        self._tracked_fps = fps
        self._tracked_calls = calls
        self._tracked_descends = self._descends_from_initial(messages, fps)
        self._candidate_fps = None

    def _descends_from_initial(
        self, messages: list[ChatMessage], fps: list["_MessageFingerprint"]
    ) -> "_Descent | None":
        """How a thread's non-system messages anchor on the initial input.

        Each initial message matches verbatim, as its condensed
        `attachment://<hash>` reference, or as decorated text that contains
        the initial message. Scaffolds transform the prompt on its way
        through their conversation store: a long prompt that rides in via
        inspect's transcript condensation crosses the bridge as the
        placeholder rather than the original text, and opencode round-trips
        the prompt wrapped in literal double quotes — the main loop must
        still anchor in both cases. Only the exact reference to the initial
        content matches (an attachment reference to other content is not a
        wildcard), and containment requires a same-role message and at least
        `_ANCHOR_CONTAINMENT_MIN_CHARS` of initial text so a trivially short
        prompt can't match a side call by coincidence.

        The verdict is graded per aligned position (see `_position_descent`)
        so `_track_state` can arbitrate between two anchored threads by
        evidence strength (see `_Descent` for the ordering rationale),
        aggregated weakness-first:

        - any position that needed generic containment caps the thread at
          `CONTAINED` — side calls copy stored (possibly quote-wrapped)
          messages too, so an interpolated position makes the whole thread
          low-confidence no matter how its other positions anchor;
        - otherwise quote-wrap at any position grades the thread `QUOTED`:
          among threads whose every position matches exactly, the store
          transform marks the persisted main conversation, and evidence at
          one position is not diluted by others that round-trip verbatim (a
          partially transformed main thread must still outrank a raw-copy
          side call);
        - otherwise `EXACT`.

        Returns `None` when there is no initial input to anchor on (descent
        can't discriminate threads, so `_track_state` falls back to the legacy
        length heuristic).
        """
        if not self._initial_fps:
            return None
        non_system = [(m, fp) for m, fp in zip(messages, fps) if fp.role != "system"]
        if len(non_system) < len(self._initial_fps):
            return _Descent.NO
        quoted = False
        contained = False
        for (message, fp), initial, condensed, initial_text in zip(
            non_system,
            self._initial_fps,
            self._initial_fps_condensed,
            self._initial_texts,
        ):
            position = _position_descent(message, fp, initial, condensed, initial_text)
            if position is _Descent.NO:
                return _Descent.NO
            quoted = quoted or position is _Descent.QUOTED
            contained = contained or position is _Descent.CONTAINED
        if contained:
            return _Descent.CONTAINED
        return _Descent.QUOTED if quoted else _Descent.EXACT


@lru_cache(maxsize=100)
def message_json_hash(message_json: str) -> str:
    return mm3_hash(message_json)


class _MessageFingerprint(NamedTuple):
    """(role, hash-of-text) identity used for thread prefix comparisons.

    Deliberately excludes message ids and metadata: messages round-trip through
    the scaffold's own conversation store between calls, so only role and text
    content are stable across the main loop's successive requests.
    """

    role: str
    text_hash: str


def _message_fingerprint(message: ChatMessage) -> _MessageFingerprint:
    return _MessageFingerprint(role=message.role, text_hash=mm3_hash(message.text))


class _Descent(IntEnum):
    """Graded descent-from-initial-input verdict (see `_descends_from_initial`).

    Ordered by strength of evidence that the thread is the *main*
    conversation, so `_track_state` can arbitrate between two descending
    threads. `QUOTED` (nothing but the initial input in literal double
    quotes) sits above `EXACT`: quote-wrap is the scaffold's conversation-
    store transform, so it can only come from the persisted main thread,
    whereas a verbatim resend is also what side calls produce by copying the
    raw input (topic detectors, title preambles). Generic containment ranks
    below both — any call that interpolates the prompt into other text
    produces it.

    `QUOTED` > `EXACT` is a deliberate trade with a mirrored residual
    ambiguity: under a scaffold that does *not* quote-wrap its store, a
    side call whose whole aligned message is exactly the quoted prompt
    presents the same observables as opencode's quote-wrapped main vs a
    raw-copy side call (one QUOTED one-shot, one EXACT one-shot), so any
    static ordering fails exactly one of the two shapes. This ordering
    sacrifices the bare-quoted side call — a constructed shape, no scaffold
    observed producing it — to protect the observed opencode failure;
    demoting QUOTED to tie EXACT breaks the observed shape in three test
    pairs while still failing one order of the constructed one. Exposure is
    one-shot mains only (the calls/length gate in `_track_state` protects
    established threads, and a multi-turn main reclaims tracking via
    candidate promotion); the losing side is pinned by the
    `test_bare_quoted_side_call_*` tests. Resolving the pair outright
    requires out-of-band knowledge of the scaffold's store transform (a
    bridge-caller declaration) rather than more signal at this layer.
    """

    NO = 0
    CONTAINED = 1
    EXACT = 2
    QUOTED = 3


_ANCHOR_CONTAINMENT_MIN_CHARS = 20
"""Minimum initial-message length for containment anchoring.

Below this, a side call could contain the initial text by coincidence (e.g.
a bash path-detection call quoting a short command prompt) and be adopted as
the descending thread; such short prompts anchor by exact/condensed match
or by exact quote-wrapping only (see `_position_descent`).
"""


def _position_descent(
    message: ChatMessage,
    fp: _MessageFingerprint,
    initial: _MessageFingerprint,
    condensed: _MessageFingerprint,
    initial_text: str,
) -> "_Descent":
    """Grade how one aligned message anchors on its initial counterpart.

    Scaffolds decorate the prompt as it round-trips their conversation store
    (opencode wraps it in literal double quotes; others prepend headers), so
    exact-text anchoring alone misses the main loop. Beyond the verbatim and
    condensed ``attachment://<hash>`` forms, a same-role message anchors as
    `QUOTED` when it is exactly the initial text (or its condensed
    reference, since decoration composes with transcript condensation) in
    double quotes, and as `CONTAINED` when it contains the initial text
    inside other content. `initial_text` is pre-stripped (in `__init__`) and
    the quote *interior* is stripped before comparison: the scaffold quotes
    the original prompt, so whitespace around the task survives inside the
    wrapper (`"  task  "`) while trimming by the scaffold removes it —
    neither may defeat matching.

    Generic containment requires `_ANCHOR_CONTAINMENT_MIN_CHARS` of initial
    text so a trivially short prompt can't match a side call by coincidence;
    the quoted and condensed forms are exempt from the floor because they
    can't match by coincidence (nothing but the quoted prompt / a content
    hash). An attachment reference to other content is not a wildcard — only
    the exact reference to the initial content matches.
    """
    if fp == initial or fp == condensed:
        return _Descent.EXACT
    if fp.role != initial.role:
        return _Descent.NO
    stripped = message.text.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        interior = stripped[1:-1].strip()
        if interior == f"{ATTACHMENT_PROTOCOL}{initial.text_hash}" or (
            initial_text and interior == initial_text
        ):
            return _Descent.QUOTED
    if (
        len(initial_text) >= _ANCHOR_CONTAINMENT_MIN_CHARS
        and initial_text in message.text
    ) or f"{ATTACHMENT_PROTOCOL}{initial.text_hash}" in message.text:
        return _Descent.CONTAINED
    return _Descent.NO


def _condensed_fingerprint(fp: _MessageFingerprint) -> _MessageFingerprint:
    """Fingerprint of the same message condensed to an attachment reference.

    Transcript condensation replaces long text with
    ``attachment://<mm3-hash-of-text>`` (see `inspect_ai.log._condense`);
    since the attachment id is the same mm3 hash a fingerprint stores, the
    condensed form is computable from the fingerprint alone.
    """
    return _MessageFingerprint(
        role=fp.role, text_hash=mm3_hash(f"{ATTACHMENT_PROTOCOL}{fp.text_hash}")
    )


def _extends(prefix: list[_MessageFingerprint], fps: list[_MessageFingerprint]) -> bool:
    """Whether `fps` is a proper extension (continuation) of `prefix`."""
    return len(fps) > len(prefix) and fps[: len(prefix)] == prefix
