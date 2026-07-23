from functools import lru_cache
from typing import NamedTuple, Sequence, Set

from shortuuid import uuid

from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent._agent import AgentState
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
        checkpointer: Checkpointer | None = None,
    ) -> None:
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
        self._compaction = compaction
        self._compact: Compact | None = None
        self._last_message_count = 0
        # thread-tracking state for _track_state (see its docstring). the
        # descent anchor is the initial input (via _compaction_prefix, which
        # restores to the original input on checkpoint resume).
        self._initial_fps = [
            _message_fingerprint(m)
            for m in self._compaction_prefix
            if m.role != "system"
        ]
        self._tracked_fps: list[_MessageFingerprint] | None = None
        self._tracked_calls = 0
        self._tracked_descends: bool | None = None
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
          start with the initial input's non-system messages. A descending
          thread displaces a tracked non-descending thread when that thread is
          a one-shot call (the opencode title case) or when the descending
          call is longer than the tracked thread (the main loop reclaiming
          tracking from a promoted sub-agent loop, below). A non-descending
          call never directly
          displaces a tracked descending thread (side calls, sub-agent
          loops).
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
            descends = self._descends_from_initial(fps)
            if (
                descends is True
                and self._tracked_descends is False
                and (self._tracked_calls == 1 or len(messages) > len(self._tracked_fps))
            ):
                # the real conversation displacing a non-descending thread:
                # a one-shot side call that landed first (the opencode title
                # case) or, when longer than the tracked thread, a promoted
                # multi-call sub-agent loop (a main loop resuming with a
                # single final call would otherwise be parked as a candidate
                # that nothing extends). a short stray descending one-shot
                # still can't displace an established non-descending thread
                # (flapping guard).
                self._adopt_thread(messages, output, fps, calls=1)
            elif descends == self._tracked_descends and len(messages) > (
                len(self._tracked_fps) if descends is True else self._last_message_count
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
        descending thread may displace a non-descending one-shot (`calls == 1`)
        thread regardless of length.
        """
        self.state.messages = messages
        self.state.output = output
        self._tracked_fps = fps
        self._tracked_calls = calls
        self._tracked_descends = self._descends_from_initial(fps)
        self._candidate_fps = None

    def _descends_from_initial(self, fps: list["_MessageFingerprint"]) -> bool | None:
        """Whether a thread's non-system messages start with the initial input.

        Returns `None` when there is no initial input to anchor on (descent
        can't discriminate threads, so `_track_state` falls back to the legacy
        length heuristic).
        """
        if not self._initial_fps:
            return None
        non_system = [fp for fp in fps if fp.role != "system"]
        return non_system[: len(self._initial_fps)] == self._initial_fps


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


def _extends(prefix: list[_MessageFingerprint], fps: list[_MessageFingerprint]) -> bool:
    """Whether `fps` is a proper extension (continuation) of `prefix`."""
    return len(fps) > len(prefix) and fps[: len(prefix)] == prefix
