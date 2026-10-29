import json
from enum import IntEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable, NamedTuple, NoReturn, Sequence

from shortuuid import uuid

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent._agent import AgentState
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction import (
    Compact,
    CompactionStrategy,
)
from inspect_ai.model._compaction import (
    compaction as create_compaction,
)
from inspect_ai.model._message_ids import content_hash, edit_id
from inspect_ai.model._model import (
    GenerateFilter,
    Model,
    ModelEventSink,
    ModelResolver,
    ModelResponseFilter,
)
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
    from inspect_ai.event._tool import ToolEvent


_MAX_AWAITED_RESULTS = 256
"""Host tool calls tracked for their result message, beyond which the oldest replies' are dropped."""


class _HandedCall(NamedTuple):
    """A call in a reply handed to the scaffold."""

    reply_id: str
    """Id of the reply."""

    position: int
    """The call's index in the reply."""

    calls: Sequence[ToolCall]
    """Every call in the reply, as handed to the scaffold."""

    @property
    def call(self) -> ToolCall:
        return self.calls[self.position]


class _AwaitedResult(NamedTuple):
    """A host tool call waiting for the tool message that holds its result."""

    handed: _HandedCall
    """The call, as handed to the scaffold."""

    event: "ToolEvent | None"
    """The call's execution, or `None` once settled."""

    settled: bool = False
    """Whether the call was linked or found ambiguous, so later results and executions are ignored."""


def _same_call(a: ToolCall, b: ToolCall) -> bool:
    return a.function == b.function and a.arguments == b.arguments


def _copy_calls(handed: _HandedCall, copy_calls: list[ToolCall]) -> list[ToolCall]:
    """The calls in a scaffold's copy of a reply that may be `handed`.

    The one with its id, function and arguments. When no copy call has its id
    (Google re-derives call ids), those with none of the reply's handed ids and
    its function and arguments.
    """
    call = handed.call
    if any(c.id == call.id for c in copy_calls):
        return [c for c in copy_calls if c.id == call.id and _same_call(c, call)]
    handed_ids = {c.id for c in handed.calls}
    return [c for c in copy_calls if c.id not in handed_ids and _same_call(c, call)]


def _settle(
    awaited: dict[int, _AwaitedResult], call_index: int, matches: list[ChatMessageTool]
) -> None:
    """Settle a call answered by `matches`, linking its event if exactly one answers it."""
    from inspect_ai.log._transcript import transcript

    event = awaited[call_index].event
    awaited[call_index] = awaited[call_index]._replace(event=None, settled=True)
    if len(matches) == 1 and event is not None:
        event.message_id = matches[0].id
        transcript()._event_updated(event)


def _link_identical_calls(
    awaited: dict[int, _AwaitedResult],
    call_index: int,
    same: list[ToolCall],
    copy_calls: list[ToolCall],
    results: list[ChatMessageTool],
) -> None:
    """Link a group of calls the copy can't tell apart by position, if their results are equal.

    The group is every handed call with the function and arguments of call
    `call_index`; `same` are the copy calls that may be any of them.
    """
    handed = awaited[call_index].handed
    group = [i for i, call in enumerate(handed.calls) if _same_call(call, handed.call)]
    events = [entry.event if (entry := awaited.get(i)) else None for i in group]
    if len(same) != len(group) or None in events:
        return
    outcomes = {
        (to_json_str_safe(event.result), to_json_str_safe(event.error))
        for event in events
        if event is not None
    }
    copy_ids = [c.id for c in copy_calls]
    answers = [[r for r in results if r.tool_call_id == c.id] for c in same]
    if (
        len(outcomes) != 1
        or any(copy_ids.count(c.id) != 1 for c in same)
        or any(len(matches) != 1 for matches in answers)
    ):
        return
    for i, matches in zip(group, answers):
        _settle(awaited, i, matches)


class DispatchedCall(NamedTuple):
    """A bridged tool call the model made through a scaffold's dispatcher function."""

    server: str
    """The bridged server the target tool is registered under."""

    target: ToolCall
    """The call to the bridged tool itself, under the dispatcher call's id."""

    dispatch: Callable[[dict[str, Any]], dict[str, Any]]
    """Arguments for the dispatcher call that make the target call with the given ones."""


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
        allow_remote_media: bool = False,
        model_resolver: ModelResolver | None = None,
        allow_client_model_names: bool = False,
        response_filter: ModelResponseFilter | None = None,
    ) -> None:
        # Capabilities a client-declared request may reach for. Media and
        # client-chosen model names default closed so new bridge subclasses
        # cannot accidentally grant host I/O or host credentials. The known
        # in-process factory grants them explicitly.
        self.allow_remote_mcp = allow_remote_mcp
        self.allow_remote_media = allow_remote_media
        self.allow_client_model_names = allow_client_model_names
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
        # checkpointed hashes: changing `content_hash` or `edit_id` changes what a
        # resumed sample matches against
        self._content_by_id = self._cp.track(
            "bridge_message_content",
            lambda: self._content_by_id,
            {},
            value_type=dict[str, str],
        )
        self._keys_by_id: dict[str, set[str]] = {}
        for key, ids in self._message_ids.items():
            for id in ids:
                self._keys_by_id.setdefault(id, set()).add(key)
        self._record_input_message_ids(self._compaction_prefix)
        # the tracked thread's ids, from the checkpoint on resume (which isn't
        # handed back to the scaffold, see above)
        self._tracked_ids = [
            (m.id, m.role) for m in restored_messages if m.id is not None
        ]
        self.filter = filter
        self.response_filter = response_filter
        self.retry_refusals = retry_refusals
        self.model = model
        self.model_aliases: dict[str, str | Model] = model_aliases or {}
        self.model_resolver = model_resolver
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
        self._awaited_results: dict[str, dict[int, _AwaitedResult]] = {}
        self._operator_keys: set[str] = set()
        self._warned_request_settings: set[str] = set()

    state: AgentState
    """State updated from messages traveling over the bridge."""

    filter: GenerateFilter | None
    """Filter for bridge model generation.

    A filter may substitute for the default model generation by returning a ModelOutput or return None to allow default processing to continue.
    """

    response_filter: ModelResponseFilter | None
    """Filter that can replace model output after generation (see ``ModelResponseFilter``).

    Return ``None`` to pass through; return a ``ModelOutput`` to replace the response.
    """

    model: str | None
    """Model that serves every request the bridge does not otherwise recognise
    (e.g. ``"inspect/openai/gpt-6-luna"``; the ``inspect/`` prefix is optional).
    Aliases, resolver results and the name ``"inspect"`` are not pinned.
    ``None`` (or ``"inspect"``) serves such requests with the eval's active
    model, or with the model the name implies when
    ``allow_client_model_names`` is set.
    """

    model_aliases: dict[str, str | Model]
    """Map of model name aliases.  When a request uses a name that appears
    here, the corresponding value (a ``Model`` instance or model spec string)
    is used instead.  Checked before the pinned ``model``.
    """

    model_resolver: ModelResolver | None
    """Dynamic per-request model routing policy.  Called with the requested
    model name after ``model_aliases`` and before the pinned ``model``;
    returning a ``Model``/spec routes the request there, ``None`` defers to the
    rest of the resolution.  Lets a bridge route by policy without enumerating
    every name.
    """

    allow_client_model_names: bool
    """Let a requested name the bridge does not otherwise recognise reach the
    model role or model it names (e.g. ``"inspect/openai/gpt-6-luna"``).  When
    ``False`` (the default), such requests are served by the eval's active
    model.  Set by the in-process ``agent_bridge()``, whose agent already has
    the host's credentials.
    """

    model_event_sink: ModelEventSink | None
    """Optional sink that takes ownership of `ModelEvent` emission for calls
    routed through the bridge. When set, the bridge installs it around
    `model.generate()`. The sink's optional `on_start` decides under which span
    each generation runs, which a live sentinel's conversation follows;
    `_record_model_interaction` dispatches pending / complete events to the
    sink, which decides when each is emitted to the transcript. Use this to
    attribute bridge model events to externally-managed agent spans (e.g.
    spans driven by a side-channel event stream). See `ModelEventSink`.
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
        sample runner. A `SandboxAgentBridge`'s generations run in the sandbox
        service task: there the raise reaches the service dispatcher, which answers
        the RPC and propagates the termination out of the service task, unwinding
        the bridge's task group.
        """
        raise TerminateSampleError(reason)

    def request_fail(self, error: Exception) -> None:
        """Fail the sample with `error` from a bridged generation.

        The caller then raises `error`, which propagates out through the agent to
        the sample runner, so an in-process bridge has nothing to do here.
        `SandboxAgentBridge` overrides this to signal its monitor task, since the
        sandbox service dispatcher turns a raise (other than a limit or a
        termination) into an RPC error that never reaches the sample runner.
        """

    grants_tool_execution: bool = False
    """Whether this bridge binds host-tool execution to the calls in each response.

    In-process bridges execute no host tools through a separate service, so nothing
    is granted or checked. `SandboxAgentBridge` sets this and overrides
    `register_tool_execution_grants`; `apply_bridge_tool_approval` reads it to
    decide whether alternate choices must be dropped without an approval policy.
    """

    def register_tool_execution_grants(
        self,
        calls: Sequence[ToolCall],
        tools: Sequence[ToolInfo | Tool],
        *,
        span_id: str | None = None,
    ) -> None:
        """Register the calls in a response handed to the scaffold for execution-edge checks.

        `tools` are the declarations the scaffold made to the model in the request
        that produced the response; a subclass overriding this hook must accept
        them (the parameter is new, and required, since the calls cannot be
        resolved without it). `span_id` is the span the proposing `ModelEvent`
        was placed in when a `ModelEventSink` put it somewhere other than the
        current span, else `None`; an override must accept it too, as
        `bridge_generate` passes it for every generation. In-process bridges
        execute no host tools through a separate service, so the base
        implementation has nothing to register. Sandbox bridges override this to
        bind later service requests to the calls the model actually made.
        """

    _proposing_message_ids: dict[str, str] = {}
    """Generated output message id by call id, for the calls `register_tool_execution_grants` is registering.

    Set by `bridge_generate` around the call (the hook's signature is public). A
    call a response filter added has none.
    """

    _proposing_reply_id: str | None = None
    """Id of the reply handed to the scaffold, while `register_tool_execution_grants` registers its calls."""

    def _await_result_message(self, handed: _HandedCall, event: "ToolEvent") -> None:
        """Set `event.message_id` when the scaffold first sends the result of `handed`.

        The result reaches the bridge only when the scaffold sends it back in a
        later request (`_link_result_messages`). A second execution of the call
        settles it unlinked (which execution the result holds is unknown), and
        one after the call settled stays unlinked. At most `_MAX_AWAITED_RESULTS`
        calls are tracked; the oldest replies' calls are dropped (left unlinked)
        beyond that.
        """
        calls = self._awaited_results.setdefault(handed.reply_id, {})
        tracked = calls.get(handed.position)
        if tracked is None:
            calls[handed.position] = _AwaitedResult(handed, event)
        elif not tracked.settled:
            calls[handed.position] = tracked._replace(event=None, settled=True)
        tracked_calls = sum(len(calls) for calls in self._awaited_results.values())
        while tracked_calls > _MAX_AWAITED_RESULTS:
            oldest = next(iter(self._awaited_results))
            tracked_calls -= len(self._awaited_results.pop(oldest))

    def _link_result_messages(
        self, messages: list[ChatMessage], recognized: list[str | None]
    ) -> None:
        """Link awaited host tool events to their result messages in a request.

        `recognized` is the id each message was recognized by (before an edit
        versioned it). A reply handed to the scaffold comes back as the assistant
        message recognized by its id. In that copy, a call is the one with its id,
        function and arguments (`_copy_calls`), picked by no other awaited call
        and with an id unique in the copy. Its result is a tool message before
        the next assistant message answering that id: exactly one links it, more
        than one settles it unlinked.

        Where the copy re-derives call ids (Google), calls with the same function
        and arguments can't be told apart. They link by position only when there
        are as many in the copy as were handed over, each executed once with the
        same result and error, and each copy call is answered by exactly one tool
        message (`_link_identical_calls`): any pairing then gives each event a
        message holding its result.

        Each call settles on its own. One the copy can't identify, or with no
        result yet, keeps waiting: results sent in separate requests, after
        another assistant message, or after a side call without them still link.
        A missing result is never taken as abandoned; `_MAX_AWAITED_RESULTS`
        bounds calls whose results never come.
        """
        if not self._awaited_results:
            return
        for index, (message, reply_id) in enumerate(zip(messages, recognized)):
            if reply_id is None or not isinstance(message, ChatMessageAssistant):
                continue
            awaited = self._awaited_results.get(reply_id)
            if awaited is None:
                continue
            results: list[ChatMessageTool] = []
            for following in messages[index + 1 :]:
                if isinstance(following, ChatMessageAssistant):
                    break
                if isinstance(following, ChatMessageTool):
                    results.append(following)
            copy_calls = message.tool_calls or []
            candidates = {
                call_index: _copy_calls(entry.handed, copy_calls)
                for call_index, entry in awaited.items()
                if not entry.settled
            }
            identified = {
                call_index: same[0]
                for call_index, same in candidates.items()
                if len(same) == 1
            }
            for call_index, copy_call in identified.items():
                if (
                    sum(c is copy_call for c in identified.values()) != 1
                    or [c.id for c in copy_calls].count(copy_call.id) != 1
                ):
                    continue
                matches = [r for r in results if r.tool_call_id == copy_call.id]
                if matches:
                    _settle(awaited, call_index, matches)
            for call_index, same in candidates.items():
                if len(same) > 1 and not awaited[call_index].settled:
                    _link_identical_calls(
                        awaited, call_index, same, copy_calls, results
                    )

    def dispatched_call(self, call: ToolCall) -> DispatchedCall | None:
        """The bridged tool call that `call` makes through a dispatcher, if any.

        Some scaffolds reach every bridged tool through one function whose arguments
        name the target. Approval reviews such a call as the target call, so policies
        match the bridged tool's own name and approvers see (and modify) its own
        arguments. In-process bridges have no bridged tools, so nothing is
        dispatched; `SandboxAgentBridge` overrides this.
        """
        return None

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

    def _assign_message_ids(self, messages: list[ChatMessage]) -> None:
        """Give each message of a request the id the bridge knows it by, or a new one.

        Messages that line up with the tracked thread (`_align_with_tracked`) take
        its ids. Others take the first id recorded for their strongest key that
        isn't already used in the request, so the k-th repeat of a message gets the
        k-th id.
        """
        keys = [_message_id_keys(message) for message in messages]
        aligned = self._align_with_tracked(messages, keys)
        reserved = set(aligned.values())
        used: set[str] = set()
        # per key, the first recorded id not yet taken (ids only become taken)
        cursors: dict[str, int] = {}

        def recorded_id(message_keys: list[str]) -> str | None:
            for key in message_keys:
                ids = self._message_ids.get(key, [])
                cursor = cursors.get(key, 0)
                while cursor < len(ids) and (
                    ids[cursor] in used or ids[cursor] in reserved
                ):
                    cursor += 1
                cursors[key] = cursor
                if cursor < len(ids):
                    return ids[cursor]
            return None

        recognized: list[str | None] = []
        for index, (message, message_keys) in enumerate(zip(messages, keys)):
            message_id = aligned.get(index) or recorded_id(message_keys)
            recognized.append(message_id)
            if message_id is None:
                message.id = uuid()
                self._content_by_id[message.id] = content_hash(message)
            else:
                used.add(message_id)
                message.id = self._version_id(message_id, message)
            used.add(message.id)
            self._record_message_id(message_keys, message.id)
        self._link_result_messages(messages, recognized)

    def _version_id(self, message_id: str, message: ChatMessage) -> str:
        """`message_id`, or the id of an edited version if `message`'s content differs.

        Different content never shares an id. A scaffold that sends a message back
        changed (even in whitespace) has edited it: the edit gets an id derived
        from the id it was recognized by and its content.
        """
        content = content_hash(message)
        if self._content_by_id.setdefault(message_id, content) == content:
            return message_id
        edited_id = edit_id(message_id, content)
        self._content_by_id.setdefault(edited_id, content)
        return edited_id

    def _align_with_tracked(
        self, messages: list[ChatMessage], keys: list[list[str]]
    ) -> dict[int, str]:
        """Pair request messages with the tracked thread's, in order.

        Each run of consecutive matches starts at the tracked message sharing the
        strongest key, then the longest run (one that reaches the end of the
        tracked thread continues it), then the latest position (scaffold
        compaction keeps the tail). A same-role message between two runs, at the
        same offset in both, is an edit of the tracked one.

        Only the position continuing the last run and the latest
        `_MAX_ALIGN_CANDIDATES` positions per key are considered, and runs are
        measured only for the strongest, so the cost stays linear in the length
        of a conversation that repeats the same messages.
        """
        tracked = self._tracked_ids
        tracked_keys = [self._keys_by_id.get(id, set()) for id, _ in tracked]
        positions: dict[str, list[int]] = {}
        for position, position_keys in enumerate(tracked_keys):
            for key in position_keys:
                positions.setdefault(key, []).append(position)

        def strength(i: int, j: int) -> int:
            return max(
                (_key_strength(key) for key in keys[i] if key in tracked_keys[j]),
                default=0,
            )

        def run(i: int, j: int) -> int:
            length = 0
            while (
                i + length < len(messages)
                and j + length < len(tracked)
                and strength(i + length, j + length)
            ):
                length += 1
            return length

        aligned: dict[int, str] = {}
        i, next_j = 0, 0
        last: tuple[int, int] | None = None
        while i < len(messages):
            diagonal = next_j + (i - last[0]) if last is not None else i
            candidates = {
                j
                for key in keys[i]
                for j in positions.get(key, [])[-_MAX_ALIGN_CANDIDATES:]
                if j >= next_j
            }
            if diagonal < len(tracked) and strength(i, diagonal):
                candidates.add(diagonal)
            if not candidates:
                i += 1
                continue
            strengths = {j: strength(i, j) for j in candidates}
            strongest = max(strengths.values())
            runs = {j: run(i, j) for j in candidates if strengths[j] == strongest}
            j = max(
                runs,
                key=lambda j: (
                    len(messages) - i if j + runs[j] == len(tracked) else runs[j],
                    j,
                ),
            )
            if last is not None and i - last[0] == j - last[1]:
                for offset in range(i - last[0]):
                    gap_id, gap_role = tracked[last[1] + offset]
                    if messages[last[0] + offset].role == gap_role:
                        aligned[last[0] + offset] = gap_id
            length = runs[j]
            for offset in range(length):
                aligned[i + offset] = tracked[j + offset][0]
            i, next_j = i + length, j + length
            last = (i, next_j)
        return aligned

    def _record_message_id(self, keys: list[str], message_id: str) -> None:
        # `_keys_by_id` mirrors `_message_ids`, so membership is a set lookup
        known = self._keys_by_id.setdefault(message_id, set())
        for key in keys:
            if key not in known:
                self._message_ids.setdefault(key, []).append(message_id)
                known.add(key)

    def _record_input_message_ids(self, messages: list[ChatMessage]) -> None:
        """Record the input's ids, including the condensed and quoted forms `_position_descent` accepts."""
        for message in messages:
            if message.id is None:
                continue
            keys = _message_id_keys(message)
            if message.role == "user" and message.text:
                text = message.text.strip()
                for variant in (
                    f"{ATTACHMENT_PROTOCOL}{mm3_hash(message.text)}",
                    f'"{text}"',
                ):
                    keys.append(_loose_message_key(message, variant))
            self._record_message_id(keys, message.id)
            self._content_by_id.setdefault(message.id, content_hash(message))

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
        if output.message.id is not None:
            self._record_message_id(_message_id_keys(output.message), output.message.id)
            self._content_by_id.setdefault(
                output.message.id, content_hash(output.message)
            )

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
        self._tracked_ids = [(m.id, m.role) for m in messages if m.id is not None]
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


def _message_id_keys(message: ChatMessage) -> list[str]:
    """Keys a message sent back by a scaffold is recognized by, strongest first.

    Scaffolds don't echo message ids. Besides the exact content, an assistant
    message keeps its tool call ids (every dialect but Google), a tool message
    its call id, and the loose key
    ignores whitespace, JSON key order, call ids and reasoning.
    """
    keys = [
        message_json_hash(to_json_str_safe(message.model_copy(update={"id": None})))
    ]
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        keys.append("calls:" + "\n".join(call.id for call in message.tool_calls))
    if isinstance(message, ChatMessageTool) and message.tool_call_id:
        keys.append(f"result:{message.tool_call_id}")
    keys.append(_loose_message_key(message, message.text))
    return keys


_MAX_ALIGN_CANDIDATES = 8


def _key_strength(key: str) -> int:
    if key.startswith("loose:"):
        return 1
    if key.startswith(("calls:", "result:")):
        return 2
    return 3


def _loose_message_key(message: ChatMessage, text: str) -> str:
    content = [] if isinstance(message.content, str) else message.content
    return "loose:" + mm3_hash(
        json.dumps(
            [
                message.role,
                " ".join(text.split()),
                message.tool_call_id if isinstance(message, ChatMessageTool) else None,
                [
                    [
                        call.function,
                        json.dumps(call.arguments, sort_keys=True, default=str),
                    ]
                    for call in message.tool_calls or []
                ]
                if isinstance(message, ChatMessageAssistant)
                else None,
                [
                    c.id
                    if isinstance(c, ContentToolUse)
                    else c.model_dump_json(exclude_none=True)
                    for c in content
                    if not isinstance(c, ContentText | ContentReasoning)
                ],
            ],
            default=str,
        )
    )


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
