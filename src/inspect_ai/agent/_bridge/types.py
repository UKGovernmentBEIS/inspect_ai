from contextvars import ContextVar
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from typing import TYPE_CHECKING, NamedTuple, NoReturn, Sequence, Set

from shortuuid import uuid

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent._agent import AgentState
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
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
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util._checkpoint.checkpointer import Checkpointer
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer

if TYPE_CHECKING:
    # deferred: `_bridge.types` is imported at the top of `inspect_ai.agent`, well
    # before `inspect_ai.approval` can be initialized (approval -> event -> scorer
    # cycles back through partially-initialized modules). Same reason
    # `model/_call_tools.py` defers it.
    from inspect_ai.approval._policy import ApprovalPolicy
    from inspect_ai.event import ModelEvent


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
        accumulate_conversations: bool = False,
        checkpointer: Checkpointer | None = None,
        allow_remote_mcp: bool = True,
        allow_remote_media: bool = False,
    ) -> None:
        # Capabilities a client-declared request may reach for. Media defaults
        # closed so new bridge subclasses cannot accidentally grant host I/O.
        # The known in-process factory grants it explicitly.
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
        self._candidate_messages: list[ChatMessage] | None = None
        self._pending_operator = 0
        # accumulation state for _accumulate_conversation (see its docstring). Adopted on
        # ANY resume, unlike bridge_messages above: the scaffold replays only the
        # conversation it was in, so dropping the rest would lose every earlier one for
        # good -- and they are the whole point of accumulating. Replays do not duplicate,
        # because a call equal to or contained in a stored conversation is absorbed rather
        # than appended.
        self._accumulate_conversations = accumulate_conversations
        self._conversations: list[_Conversation] = self._cp.track(
            "bridge_conversations",
            lambda: self._conversations,
            [],
            value_type=list[_Conversation],
        )
        self._operator_keys: set[str] = set()
        # Span emission for accumulated conversations. The emitter owns the
        # `span_id`/`ordinal`/`first_seen_call`/`resume_adopted` fields on
        # `_Conversation`; the accumulator owns `key`/`messages`/`output`. It
        # runs whenever conversations accumulate. A caller-supplied sink does
        # not disable it -- the two compose: the sink keeps deciding when and
        # under which span an event is written (sub-agent identity a native
        # harness recovers from its own records), and the emitter attributes
        # the events the sink wrote to their conversation's span. Disabling
        # emission when a sink was present left every native-harness run
        # (all four wrappers install one) span-less, carried by flattening
        # alone.
        self._span_emitter: _ConversationSpanEmitter | None = None
        if accumulate_conversations:
            self._span_emitter = _ConversationSpanEmitter(
                self, writes_events=model_event_sink is None
            )
            self.model_event_sink = (
                self._span_emitter
                if model_event_sink is None
                else _ComposedModelEventSink(self._span_emitter, model_event_sink)
            )
        # Conversations restored from a checkpoint predate this process: the spans
        # that carried their events closed with the process that opened them, so the
        # next call continuing one mints a fresh span, marked by `resume_adopted`.
        # A legacy snapshot (written before span emission existed) restores every
        # conversation with default span metadata; first-seen order survives as the
        # list order, so ordinals are re-derived from it. `first_seen_call` is
        # process-local and unknowable across the boundary: zeroed, with
        # `resume_adopted` marking the discontinuity.
        legacy_ordinals = len(self._conversations) > 1 and all(
            conversation.ordinal == 0 for conversation in self._conversations
        )
        for index, conversation in enumerate(self._conversations):
            conversation.span_id = None
            conversation.resume_adopted = True
            conversation.first_seen_call = 0
            if legacy_ordinals:
                conversation.ordinal = index

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

    def close_conversation_spans(self) -> None:
        """End every accumulated conversation's span (no-op without accumulation)."""
        if self._span_emitter is not None:
            self._span_emitter.close()

    def request_terminate(self, reason: str) -> NoReturn:
        """Terminate the sample from a bridged generation.

        Raises `TerminateSampleError`, which propagates out through the agent to the
        sample runner. `SandboxAgentBridge` overrides this: its generations run in
        the sandbox service task, where exceptions become RPC error responses instead
        of propagating.
        """
        raise TerminateSampleError(reason)

    def register_tool_execution_grants(self, calls: Sequence[ToolCall]) -> None:
        """Register calls from an approved response for execution-edge checks.

        In-process bridges execute no host tools through a separate service, so the
        base implementation has nothing to register. Sandbox bridges override this
        to bind later service requests to the calls approval actually reviewed.
        """

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

        When `accumulate_conversations` is set, none of the above applies: every
        conversation observed over the bridge is kept and concatenated instead of
        one being chosen. See `_accumulate_conversation`.
        """
        if self._accumulate_conversations:
            self._accumulate_conversation(input, output)
            await self._cp.tick()
            return
        messages = input + [output.message]
        fps = [_message_fingerprint(m) for m in messages]

        if self._tracked_fps is None:
            # first observed call: best information available so far (if it is
            # a side call the rules below displace it later)
            self._adopt_thread(messages, output, fps, calls=1)
        elif _extends(self._tracked_fps, fps):
            messages = _preserve_producer_messages(self.state.messages, messages)
            self._adopt_thread(messages, output, fps, calls=self._tracked_calls + 1)
        elif self._candidate_fps is not None and _extends(self._candidate_fps, fps):
            # the candidate got continued so it is a live agent loop (e.g. the
            # post-compaction conversation): promote it over the tracked thread
            messages = _preserve_producer_messages(
                self._candidate_messages or [], messages
            )
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
                self._candidate_messages = messages

        self._last_message_count = len(messages)

        # tick the checkpointer
        await self._cp.tick()

    def _accumulate_conversation(
        self, input: list[ChatMessage], output: ModelOutput
    ) -> None:
        """Keep EVERY conversation observed over the bridge, not just the main one.

        `_track_state` chooses one "main" thread because a scaffold runs one agent
        loop and its side calls are noise. A sandbox is not a scaffold: nothing
        constrains it to one conversation, and a human-driven or multi-invocation
        harness routinely runs several independent ones through the same bridge (for
        example an operator running `claude -p` several times). Choosing one then
        silently discards the rest, and the discarded ones exist nowhere in the
        resulting sample.

        A call is matched to the conversation it CONTINUES: the one whose messages are
        a prefix of this call's, longest first. Matching ignores only system prompts,
        which scaffolds may rewrite per request (Claude Code stamps a per-request cache
        token into them). Non-system message identity includes full content plus tool
        calls and tool results, so visually identical operations do not collapse.

        "Prefix" is deliberately not-strict, and re-sends are absorbed rather than
        appended, because a repeat is not a new conversation. A call identical to one
        already stored REPLACES it, and a call already CONTAINED in a stored
        conversation is dropped. Requiring a strict extension instead forks a whole
        replica on any exact repeat -- two invocations making the same deterministic
        aux call (Claude Code's bash-path probe) fingerprint identically -- and the
        fork can never re-merge, so it strands a permanent stale duplicate whose tail
        then sits at the end of `state.messages`.

        Only genuinely new work starts a conversation. That still admits a one-shot
        side call, because without a session identifier a real one-shot invocation is
        indistinguishable from an aux call and dropping it loses real work; and two
        calls sharing a history but answering DIFFERENTLY stay separate, since merging
        them would invent a conversation in which one prompt drew two consecutive
        replies.

        `state.output` is this call, not the last conversation's: conversations keep
        first-seen order, so a call resuming an earlier one leaves `state.messages`
        ending on a later conversation. Order is the property this option exists to
        provide, so it wins, and `state.messages[-1]` is not guaranteed to be
        `state.output`'s message. Indexing output by conversation order instead lets a
        single late side call poison it for the rest of the run.
        """
        messages = input + [output.message]
        key = _non_system([_conversation_message_fingerprint(m) for m in messages])
        call_index = (
            self._span_emitter.next_call_index()
            if self._span_emitter is not None
            else 0
        )
        continued: int | None = None
        for index, conversation in enumerate(self._conversations):
            if _is_prefix(conversation.key, key) and (
                continued is None
                or len(conversation.key) > len(self._conversations[continued].key)
            ):
                continued = index
        if continued is None:
            # A call already covered by a stored conversation (a re-send of an
            # earlier turn) carries nothing the longer form does not: it joins
            # that conversation rather than storing a replica.
            current: _Conversation | None = None
            for conversation in self._conversations:
                if _is_prefix(key, conversation.key) and (
                    current is None or len(conversation.key) > len(current.key)
                ):
                    current = conversation
            if current is None:
                current = _Conversation(
                    key=key,
                    messages=messages,
                    output=output,
                    ordinal=1
                    + max((c.ordinal for c in self._conversations), default=-1),
                    first_seen_call=call_index,
                )
                self._conversations.append(current)
        else:
            prior = self._conversations[continued]
            messages = _preserve_producer_messages(prior.messages, messages)
            current = _Conversation(
                key=key,
                messages=messages,
                output=output,
                span_id=prior.span_id,
                ordinal=prior.ordinal,
                first_seen_call=prior.first_seen_call,
                resume_adopted=prior.resume_adopted,
            )
            self._conversations[continued] = current
            # Absorb any other conversation this one now contains, so a fork that
            # happened before the two met cannot persist as a stale duplicate. An
            # absorbed conversation's span (if any) ends now: its events stay inside
            # it, and nothing will extend it again.
            kept: list[_Conversation] = []
            for index, conversation in enumerate(self._conversations):
                if index == continued or not _is_prefix(conversation.key, key):
                    kept.append(conversation)
                elif (
                    conversation.span_id is not None and self._span_emitter is not None
                ):
                    self._span_emitter.end_span(conversation.span_id)
            self._conversations = kept
        if self._span_emitter is not None:
            self._span_emitter.attribute_call(current)
        self.state.messages = self._flattened_conversations()
        self.state.output = output

    def _flattened_conversations(self) -> list[ChatMessage]:
        """Every conversation concatenated in first-seen order, with unique message ids.

        Ids are allocated from message CONTENT (`_id_for_message`), and each request only
        ever sees its own conversation, so independent conversations that repeat a turn --
        replicas of one script, a re-asked prompt -- arrive carrying the SAME id, while
        `ChatMessage.id` is documented unique.

        A repeat is re-identified on a copy that is written BACK into its conversation, so
        the new id is allocated once and then held. Re-deriving it per call instead would
        hand the same message a different id on every generation, which defeats the id
        stability `apply_message_ids` exists to provide and breaks every consumer that
        joins on the id (`log/_condense.py`'s walk cache, `solver/_run.py`'s prefix diff,
        matching `sample.messages` back to `ModelEvent.input`).

        When a synthetic carrier collides with a bridge-produced assistant message, retain
        the producer id. The carrier is an independent input and may be re-identified; the
        output id is the identity a later `ModelEvent` uses to establish authorship.
        """
        flattened: list[ChatMessage] = []
        seen: dict[str, tuple[int, int, int]] = {}
        for conversation_index, conversation in enumerate(self._conversations):
            for position, message in enumerate(conversation.messages):
                if message.id is not None and (prior := seen.get(message.id)):
                    prior_flattened, prior_conversation, prior_position = prior
                    prior_message = flattened[prior_flattened]
                    if _is_producer(message) and not _is_producer(prior_message):
                        replacement_id = uuid()
                        prior_message = prior_message.model_copy(
                            update={"id": replacement_id}
                        )
                        self._conversations[prior_conversation].messages[
                            prior_position
                        ] = prior_message
                        flattened[prior_flattened] = prior_message
                        seen[replacement_id] = prior
                    else:
                        message = message.model_copy(update={"id": uuid()})
                        conversation.messages[position] = message
                if message.id is not None:
                    seen[message.id] = (len(flattened), conversation_index, position)
                flattened.append(message)
        return flattened

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
        self._candidate_messages = None

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


class _ConversationMessageFingerprint(NamedTuple):
    """Stable identity for accumulating one conversation's non-system messages.

    Message IDs, source, metadata, and model name are transport details that may change
    as a scaffold replays history. Every remaining field participates, preserving
    non-text content plus tool-call and tool-result identity.
    """

    role: str
    identity_hash: str


def _conversation_message_fingerprint(
    message: ChatMessage,
) -> _ConversationMessageFingerprint:
    message_identity = message.model_dump(
        exclude={"id", "metadata", "model", "source"},
        exclude_none=True,
    )
    return _ConversationMessageFingerprint(
        role=message.role,
        identity_hash=mm3_hash(to_json_str_safe(message_identity)),
    )


def _is_producer(message: ChatMessage) -> bool:
    """Whether a message is a bridge model output with attribution authority."""
    return isinstance(message, ChatMessageAssistant) and message.source == "generate"


def _preserve_producer_messages(
    previous: list[ChatMessage], messages: list[ChatMessage]
) -> list[ChatMessage]:
    """Reuse producer messages from an exactly continued non-system prefix.

    Request conversion synthesizes inbound ids, source, and metadata. Those transport
    fields cannot identify a continuation, so only semantic wire content participates.
    Systems are also excluded because native CLIs may rewrite them per request. A mismatch
    leaves the converted request untouched rather than inferring producer identity.
    """
    previous_non_system = [
        (index, message)
        for index, message in enumerate(previous)
        if message.role != "system"
    ]
    message_non_system = [
        (index, message)
        for index, message in enumerate(messages)
        if message.role != "system"
    ]
    if len(previous_non_system) > len(message_non_system):
        return messages
    if any(
        _conversation_message_fingerprint(previous_message)
        != _conversation_message_fingerprint(message)
        for (_, previous_message), (_, message) in zip(
            previous_non_system, message_non_system
        )
    ):
        return messages

    preserved = messages.copy()
    for (_, previous_message), (message_index, _) in zip(
        previous_non_system, message_non_system
    ):
        if _is_producer(previous_message):
            preserved[message_index] = previous_message
    return preserved


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


@dataclass
class _Conversation:
    """One conversation observed over the bridge (see `_accumulate_conversation`).

    `key`/`messages`/`output` are accumulator-owned; `span_id`/`ordinal`/
    `first_seen_call`/`resume_adopted` are owned by `_ConversationSpanEmitter`.
    The span fields default for snapshots written before span emission existed,
    and `span_id` is reset on every checkpoint restore (see
    `AgentBridge.__init__`).
    """

    key: list[_ConversationMessageFingerprint]
    messages: list[ChatMessage]
    output: ModelOutput
    span_id: str | None = None
    ordinal: int = 0
    first_seen_call: int = 0
    resume_adopted: bool = False


BRIDGE_CONVERSATION_SPAN_TYPE = "conversation"
"""Span type for accumulated bridge conversations.

The type consumers of bridged conversation spans already read; timeline
classification (`span_type == "agent"`) is intentionally not claimed here —
flipping the type is a consumer-visible change reserved for the release that
stops flattening conversations into `state.messages`.
"""


class _CallRecord(NamedTuple):
    """One bridged call's emitted events and their emission-time parent span.

    Lives in a task-local ContextVar: the sandbox service runs one handler task
    per request, so the record's lifetime is exactly the call's — a handler
    that fails before accumulating dies with its record, leaking nothing and
    never mis-attributing to a reused task id.
    """

    parent_id: str | None
    events: list["ModelEvent"]


_call_record: ContextVar[_CallRecord | None] = ContextVar(
    "_bridge_call_record", default=None
)


class _ConversationSpanEmitter:
    """Emit one transcript span per accumulated conversation.

    Installed as the bridge's `model_event_sink` when `accumulate_conversations`
    is set, so `_record_model_interaction` routes each bridged `ModelEvent` here
    instead of emitting it to the transcript directly. The emitter does no
    conversation matching of its own: events are emitted immediately under their
    ambient span and remembered per handler task, and `_accumulate_conversation`
    — the only authoritative matcher — attributes them to the resolved
    conversation's span after each call. Attribution by task rather than by
    content is what keeps a compacted, filter-rewritten, or approval-retried
    call's events in the conversation the accumulator chose: the request task
    that generated the events is the request task that accumulates them, no
    matter how the model input was transformed in between.

    Span metadata (`conversation_ordinal`, `first_seen_call_index`,
    `resume_adopted`) rides in an `InfoEvent` emitted inside the span with
    `source="bridge_conversation"`. Producer message identity is carried by the
    message ids themselves (see `_flattened_conversations`), not repeated here.
    `first_seen_call_index` is process-local: it restarts after a resume, and
    `resume_adopted` marks the discontinuity.
    """

    def __init__(self, bridge: "AgentBridge", *, writes_events: bool = True) -> None:
        self._bridge = bridge
        self._span_ids: list[str] = []
        self._calls_seen = 0
        self._closed = False
        # Standalone, the emitter is the transcript writer for bridged events.
        # Composed with a caller sink (`_ComposedModelEventSink`), the sink
        # writes and the emitter only records membership and re-parents.
        self._writes_events = writes_events

    def on_pending(self, event: "ModelEvent") -> None:
        from inspect_ai.log._transcript import transcript

        if self._writes_events:
            transcript()._event(event)
        self.record(event)

    def on_complete(self, event: "ModelEvent") -> None:
        from inspect_ai.log._transcript import transcript

        if self._writes_events:
            transcript()._event_updated(event)

    def record(self, event: "ModelEvent") -> None:
        """Remember ``event`` as part of the handler task's bridged call.

        The parent recorded here is the span the event was emitted under, read
        before any sink has moved it: attribution runs later and a concurrent
        handler may have rotated the ambient span in between.
        """
        if self._closed:
            return
        record = _call_record.get()
        if record is None:
            record = _CallRecord(parent_id=event.span_id, events=[])
            _call_record.set(record)
        record.events.append(event)

    def next_call_index(self) -> int:
        """The zero-based index of the bridged call being accumulated."""
        index = self._calls_seen
        self._calls_seen += 1
        return index

    def attribute_call(self, conversation: _Conversation) -> None:
        """Stamp the current call's events into the conversation's span.

        Runs in the same handler task that emitted the events (the API shims
        call `_track_state` after `bridge_generate` returns), so the task-local
        record is exactly this call's events — including approval retries,
        which generate more than once before the call accumulates. A filtered
        call recorded no events; the conversation still gets its span so every
        accumulated conversation is represented in the transcript.

        Composed with a caller sink, only events the sink has already written
        are re-parented. An event the sink is still holding — a sub-agent call
        awaiting the native identity that names its span — keeps the sink's
        placement when the sink writes it: that identity is exact where the
        prefix match is not, so it is adopted in place of the conversation
        span, never alongside it as a second span for the same event.
        """
        from inspect_ai.log._transcript import transcript

        record = _call_record.get()
        _call_record.set(None)
        if self._closed:
            return
        span_id = self._ensure_span(
            conversation,
            parent_id=record.parent_id if record is not None else None,
            parent_known=record is not None,
        )
        for event in record.events if record is not None else []:
            if not self._writes_events and not transcript()._is_resident(event):
                continue
            event.span_id = span_id
            transcript()._event_updated(event)

    def end_span(self, span_id: str) -> None:
        """End one conversation's span (absorption: nothing extends it again)."""
        from inspect_ai.event import SpanEndEvent
        from inspect_ai.log._transcript import transcript

        if span_id in self._span_ids:
            self._span_ids.remove(span_id)
            transcript()._event(SpanEndEvent(id=span_id))

    def close(self) -> None:
        """End every open conversation span. Idempotent."""
        from inspect_ai.event import SpanEndEvent
        from inspect_ai.log._transcript import transcript

        if self._closed:
            return
        self._closed = True
        for span_id in reversed(self._span_ids):
            transcript()._event(SpanEndEvent(id=span_id))
        self._span_ids.clear()
        _call_record.set(None)

    def _ensure_span(
        self, conversation: _Conversation, *, parent_id: str | None, parent_known: bool
    ) -> str:
        """The conversation's span, minted on first attribution.

        A conversation without a span was just created, was restored from a
        checkpoint (its span closed with the process that opened it — the fresh
        span is the adoption `resume_adopted` records), or was created by a
        filtered call that never generated.
        """
        if conversation.span_id is None:
            conversation.span_id = self._open_span(
                conversation, parent_id=parent_id, parent_known=parent_known
            )
        return conversation.span_id

    def _open_span(
        self, conversation: _Conversation, *, parent_id: str | None, parent_known: bool
    ) -> str:
        """Open the conversation's span under its events' emission-time parent.

        The parent is the span the call's events were emitted under, recorded at
        emission: attribution runs later in the handler task, and a concurrent
        handler may have rotated the ambient checkpoint span in between — reading
        the ambient at attribution time would reparent events across checkpoints.
        A filtered call emitted nothing, so the attribution-time ambient is the
        only parent there is. `None` is legal — the span then becomes a tree
        root, which is what an unspanned sample wants.
        """
        from inspect_ai.event import InfoEvent, SpanBeginEvent
        from inspect_ai.log._transcript import transcript
        from inspect_ai.util._span import current_span_id

        if not parent_known:
            parent_id = current_span_id()
        span_id = uuid()
        begin = SpanBeginEvent(
            id=span_id,
            parent_id=parent_id,
            span_id=parent_id,
            type=BRIDGE_CONVERSATION_SPAN_TYPE,
            name=f"conversation {conversation.ordinal}",
        )
        # A captured None parent is authoritative (root span): construction fills
        # a None span_id from the ambient span, which may be an unrelated later
        # checkpoint by attribution time — restore the captured value.
        begin.span_id = parent_id
        transcript()._event(begin)
        transcript()._event(
            InfoEvent(
                source="bridge_conversation",
                span_id=span_id,
                data={
                    "conversation_ordinal": conversation.ordinal,
                    "first_seen_call_index": conversation.first_seen_call,
                    "resume_adopted": conversation.resume_adopted,
                },
            )
        )
        self._span_ids.append(span_id)
        return span_id


class _ComposedModelEventSink:
    """Route each bridged `ModelEvent` to both the span emitter and a caller sink.

    The caller's sink is the writer: it decides when the event reaches the
    transcript and under which span, exactly as it does without accumulation.
    The emitter only records the event as part of the handler task's call, so
    that `attribute_call` can move the events the sink wrote into their
    conversation's span. Recording runs first so the emitter sees the span the
    event was emitted under, before the sink has moved it.
    """

    def __init__(
        self, emitter: _ConversationSpanEmitter, sink: "ModelEventSink"
    ) -> None:
        self._emitter = emitter
        self._sink = sink

    def on_pending(self, event: "ModelEvent") -> None:
        self._emitter.record(event)
        self._sink.on_pending(event)

    def on_complete(self, event: "ModelEvent") -> None:
        self._sink.on_complete(event)


def _is_prefix(
    prefix: list[_ConversationMessageFingerprint],
    fps: list[_ConversationMessageFingerprint],
) -> bool:
    """Whether `fps` continues `prefix`, or is exactly it."""
    return len(fps) >= len(prefix) and fps[: len(prefix)] == prefix


def _non_system(
    fps: list[_ConversationMessageFingerprint],
) -> list[_ConversationMessageFingerprint]:
    """Fingerprints of the non-system messages, for conversation-continuation matching.

    A scaffold may rewrite its system prompt on every request -- Claude Code stamps a
    per-request cache token into it -- so successive calls in one conversation need not
    share a system-message fingerprint, and matching on it would make every call look
    like a new conversation.

    Used only by `_accumulate_conversation`. Main-thread tracking keeps comparing whole
    message lists: a system prompt still carries meaning there (two sub-agents can share
    a user prompt while differing only in role), and its `_extends` check is backed by the
    length and descent heuristics rather than standing alone.
    """
    return [fp for fp in fps if fp.role != "system"]


def _extends(prefix: list[_MessageFingerprint], fps: list[_MessageFingerprint]) -> bool:
    """Whether `fps` is a proper extension (continuation) of `prefix`."""
    return len(fps) > len(prefix) and fps[: len(prefix)] == prefix
