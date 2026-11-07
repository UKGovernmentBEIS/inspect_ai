import json
from collections import Counter, OrderedDict, deque
from enum import IntEnum
from functools import lru_cache, partial
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Collection,
    NamedTuple,
    NoReturn,
    Sequence,
)

from shortuuid import uuid

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai.agent._agent import AgentState
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.model._assistant_internal import copy_assistant_internal
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
from inspect_ai.model._message_ids import (
    canonical_tool_arguments,
    content_hash,
    edit_id,
)
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

_MAX_REPLY_EDIT_VERSIONS = 16
"""Recent edited reply ids retained while their calls await results."""

_MAX_RECENT_THREADS = 16
"""Recent requests and generations kept, each in place of the kept ones it extends, whose replies can contest a thread's placement (see `_contested`)."""


class _HandedCall(NamedTuple):
    """A call in a reply handed to the scaffold, as much of it as matching needs."""

    reply_id: str
    """Id of the reply."""

    position: int
    """The call's index in the reply."""

    call_id: str
    """The call's id."""

    function: str
    """The call's function."""

    arguments: str
    """Digest of the call's arguments (`_arguments_digest`)."""

    identical: int
    """Calls in the reply with this function and arguments, this one included."""

    handed_ids: frozenset[str] | None
    """Ids of every call in the reply (one set shared by its calls), or `None` for a reply of more than `_MAX_HANDED_IDS` calls."""

    id_shared: bool
    """Whether another call in the reply has this call's id."""


_MAX_HANDED_IDS = 256
"""Calls in a reply beyond which its handed ids aren't kept (its calls match only by kept id, and other replies' calls don't link while it is tracked)."""


def _arguments_digest(arguments: dict[str, Any]) -> str:
    return mm3_hash(canonical_tool_arguments(arguments))


def _handed_calls(reply_id: str, calls: Sequence[ToolCall]) -> list[_HandedCall]:
    """The calls of a reply handed to the scaffold, for `_await_result_message`."""
    keys = [(call.function, _arguments_digest(call.arguments)) for call in calls]
    ids = [call.id for call in calls]
    handed_ids = frozenset(ids) if len(calls) <= _MAX_HANDED_IDS else None
    return [
        _HandedCall(
            reply_id,
            position,
            call.id,
            *key,
            keys.count(key),
            handed_ids,
            ids.count(call.id) > 1,
        )
        for position, (call, key) in enumerate(zip(calls, keys))
    ]


class _AwaitedResult(NamedTuple):
    """A host tool call waiting for the tool message that holds its result."""

    handed: _HandedCall
    """The call, as handed to the scaffold."""

    event: "ToolEvent | None"
    """The call's execution, or `None` once settled."""

    outcome: str
    """Digest of the execution's result and error."""

    settled: bool = False
    """Whether the call was linked or found ambiguous, so later results and executions are ignored."""

    message_id: str | None = None
    """Id of the tool message the call was linked to, once settled."""

    reply_versions: tuple[str, ...] = ()
    """Recent edits of the handed reply, kept on one call per pending reply."""


def _is_handed(copy_call: ToolCall, handed: _HandedCall) -> bool:
    return (
        copy_call.function == handed.function
        and _arguments_digest(copy_call.arguments) == handed.arguments
    )


def _copy_calls(
    handed: _HandedCall, copy_calls: list[ToolCall], excluded_ids: Collection[str]
) -> list[ToolCall]:
    """The calls in a scaffold's copy of a reply that may be `handed`.

    None if another call in the reply has its id: an answer under that id
    can't be told apart. Otherwise the one with its id, function and arguments.
    When no copy call has its id (Google re-derives call ids), the ones with
    its function and arguments and an id the bridge handed in no tracked reply
    and no unexecuted proposal (`excluded_ids`), but only if `handed` is the
    reply's only call with that function and arguments and its handed ids are
    known. Identical calls can't be told apart, so they are never paired.
    """
    if handed.id_shared:
        return []
    if any(c.id == handed.call_id for c in copy_calls):
        return [
            c for c in copy_calls if c.id == handed.call_id and _is_handed(c, handed)
        ]
    if handed.identical != 1 or handed.handed_ids is None:
        return []
    return [c for c in copy_calls if c.id not in excluded_ids and _is_handed(c, handed)]


def _settle(
    awaited: dict[int, _AwaitedResult], call_index: int, matches: list[ChatMessageTool]
) -> None:
    """Settle a call answered by `matches`, linking its event if exactly one answers it."""
    from inspect_ai.log._transcript import transcript

    event = awaited[call_index].event
    linked = matches[0].id if len(matches) == 1 and event is not None else None
    awaited[call_index] = awaited[call_index]._replace(
        event=None, settled=True, message_id=linked
    )
    if event is not None and linked is not None:
        event.message_id = linked
        transcript()._event_updated(event)


class _CallDigest(NamedTuple):
    id: str
    function: str
    arguments: str
    """Digest of the call's arguments (`_arguments_digest`)."""


class _AnsweredCall(NamedTuple):
    """The call a tool message answers, as the scaffold sent the reply holding it."""

    reply_id: str
    """Id of the reply (of the handed reply, for a copy the bridge recognized)."""

    call: _CallDigest | None
    """The reply's call with the message's call id, or `None` if it has none or differing ones."""


def _answered_call(reply_id: str, copies: list[ToolCall]) -> _AnsweredCall:
    digests = {
        _CallDigest(c.id, c.function, _arguments_digest(c.arguments)) for c in copies
    }
    return _AnsweredCall(reply_id, digests.pop() if len(digests) == 1 else None)


class _Answer(NamedTuple):
    """The reply a tool message was first sent as an answer to."""

    reply_id: str

    outcomes: frozenset[str]
    """Outcomes of the call's host executions when the message was first sent."""

    linkable: bool = True
    """Whether the message may be linked to the call's host execution (not when it may be a copy of an earlier answer)."""


class _ResultId(NamedTuple):
    """The id a tool message answering a reply keeps (`None` for a new one)."""

    id: str | None

    linkable: bool
    """Whether a new id may be linked to the call's host execution (see `_Answer`)."""


class _ReplyAnswers(NamedTuple):
    """The answer records kept for a reply."""

    message_ids: list[str]
    """Tool messages first sent as its answers (keys of `_answers`)."""

    occurrences: dict[str, str]
    """Per message key, the id its answer was first given."""


_MAX_ANSWER_RECORDS = 4096
"""Answer records (`_ReplyAnswers` message ids and occurrences) kept between requests, beyond which the oldest replies' are dropped."""


class DispatchedCall(NamedTuple):
    """A bridged tool call the model made through a scaffold's dispatcher function."""

    server: str
    """The bridged server the target tool is registered under."""

    target: ToolCall
    """The call to the bridged tool itself, under the dispatcher call's id."""

    dispatch: Callable[[dict[str, Any]], dict[str, Any]]
    """Arguments for the dispatcher call that make the target call with the given ones."""


class ReviewedCalls(NamedTuple):
    """The calls approval reviews for one tool call in a bridged response."""

    calls: list[ToolCall]
    """The calls approvers see, under the tool call's id: one per bridged tool it would run."""

    dispatch: Callable[[dict[str, Any]], dict[str, Any]]
    """Arguments for the tool call that make a reviewed call with the given ones."""


def _unchanged(arguments: dict[str, Any]) -> dict[str, Any]:
    return arguments


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
        self._tracked_ids: list[tuple[str, str]] = [
            (m.id, m.role) for m in restored_messages if m.id is not None
        ]
        self._latest_generation: list[tuple[str, str]] = []
        self._latest_request: list[tuple[str, str]] = []
        self._recent_threads: deque[list[tuple[str, str]]] = deque()
        self._held: Counter[str] = Counter()
        """Kept threads (the tracked thread and recent ones) holding each reply id."""
        self._held_replies: dict[str, int] = {}
        """Per reply id, the most replies a kept thread holding it had."""
        self._dropped_reach: dict[str, int] = {}
        """Per key, the most replies a dropped thread had that held a reply with the key no kept thread holds."""
        self._keep(self._tracked_ids)
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
        self._edit_parent: dict[str, str] = {}
        self._answers: dict[str, _Answer] = {}
        self._reply_answers: OrderedDict[str, _ReplyAnswers] = OrderedDict()
        self._answer_records = 0
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

    _proposing_call_verified: list[bool] | None = None
    """Per-call filter verification, aligned with the calls being registered."""

    def _await_result_message(self, handed: _HandedCall, event: "ToolEvent") -> None:
        """Set `event.message_id` when the scaffold first sends the result of `handed`.

        The result reaches the bridge only when the scaffold sends it back in a
        later request (`_link_result_messages`). A second execution of the call
        settles it unlinked (which execution the result holds is unknown), and
        one after the call settled stays unlinked. At most `_MAX_AWAITED_RESULTS`
        calls are tracked; the oldest replies' calls are dropped (left unlinked)
        beyond that.
        """
        outcome = mm3_hash(
            to_json_str_safe({"result": event.result, "error": event.error})
        )
        calls = self._awaited_results.setdefault(handed.reply_id, {})
        tracked = calls.get(handed.position)
        if tracked is None:
            calls[handed.position] = _AwaitedResult(handed, event, outcome)
        elif not tracked.settled:
            calls[handed.position] = tracked._replace(event=None, settled=True)
        tracked_calls = sum(len(calls) for calls in self._awaited_results.values())
        while tracked_calls > _MAX_AWAITED_RESULTS:
            oldest = next(iter(self._awaited_results))
            tracked_calls -= len(self._awaited_results.pop(oldest))

    def _awaited_reply_id(
        self, reply_id: str, message: ChatMessageAssistant
    ) -> str | None:
        """Find the handed reply represented by a recognized or edited copy."""
        if reply_id in self._awaited_results:
            return reply_id
        return next(
            (
                original
                for original, calls in self._awaited_results.items()
                if any(reply_id in entry.reply_versions for entry in calls.values())
                or edit_id(original, content_hash(message)) == reply_id
            ),
            None,
        )

    def _link_result_messages(
        self,
        messages: list[ChatMessage],
        recognized: list[str | None],
        unattributed: Collection[str] = (),
    ) -> None:
        """Link awaited host tool events to their result messages in a request.

        `recognized` is the id each message was recognized by (before an edit
        versioned it). A reply handed to the scaffold comes back as the assistant
        message recognized by its id or an edited version of it. In that copy,
        a call is the one with its id,
        function and arguments (`_copy_calls`), picked by no other awaited call
        and with an id unique in the copy. Its result is a tool message before
        the next assistant message with tool calls: exactly one links it, more
        than one settles it unlinked. A message already linked to a tracked call,
        or first sent as another reply's answer (`_result_occurrence`) or as an
        answer without a linkable record (`unattributed`), isn't linked, and a
        kept id another tracked reply also handed doesn't link while that reply's call is unlinked (`_tracked_call_ids`).
        No call links while another tracked reply keeps no handed ids: any id
        in the copy could be one of that reply's unexecuted calls. A call
        matched by function and arguments doesn't take the id of a call
        proposed but not executed (`_unexecuted_call_ids`).

        Each call settles on its own. One the copy can't identify, or with no
        result yet, keeps waiting: results sent in separate requests, after
        another assistant message, or after a side call without them still link.
        A missing result is never taken as abandoned; `_MAX_AWAITED_RESULTS`
        bounds calls whose results never come.
        """
        if not self._awaited_results:
            return
        tracked_ids: dict[str, list[tuple[str, str | None]]] | None = None
        ids_unknown = {
            reply_id
            for reply_id, calls in self._awaited_results.items()
            if next(iter(calls.values())).handed.handed_ids is None
        }
        linked_ids: set[str] = set()
        excluded_ids: set[str] = set()

        def linked_result(message_id: str | None) -> bool:
            while message_id is not None:
                if message_id in linked_ids:
                    return True
                message_id = self._edit_parent.get(message_id)
            return False

        for index, (message, reply_id) in enumerate(zip(messages, recognized)):
            if reply_id is None or not isinstance(message, ChatMessageAssistant):
                continue
            original = self._awaited_reply_id(reply_id, message)
            if original is None:
                continue
            reply_id = original
            awaited = self._awaited_results[reply_id]
            first_call = next(iter(awaited))
            versions = awaited[first_call].reply_versions
            if message.id is not None and message.id != reply_id:
                awaited[first_call] = awaited[first_call]._replace(
                    reply_versions=(*versions, message.id)[-_MAX_REPLY_EDIT_VERSIONS:]
                )
            if ids_unknown - {reply_id}:
                continue
            results: list[ChatMessageTool] = []
            for following in messages[index + 1 :]:
                if isinstance(following, ChatMessageAssistant) and following.tool_calls:
                    break
                if isinstance(following, ChatMessageTool):
                    results.append(following)
            copy_calls = message.tool_calls or []
            if tracked_ids is None:
                tracked_ids = self._tracked_call_ids()
                excluded_ids = tracked_ids.keys() | self._unexecuted_call_ids()
                linked_ids = {
                    linked
                    for ids in tracked_ids.values()
                    for _, linked in ids
                    if linked
                }
            tracked = tracked_ids
            candidates = {
                call_index: _copy_calls(entry.handed, copy_calls, excluded_ids)
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
                if len(matches) == 1 and (
                    linked_result(matches[0].id)
                    or matches[0].id in unattributed
                    or self._answers_other_reply(matches[0].id, reply_id)
                    or any(
                        linked is None
                        for other, linked in tracked.get(copy_call.id, [])
                        if other != reply_id
                    )
                ):
                    continue
                if matches:
                    _settle(awaited, call_index, matches)
                    linked = awaited[call_index].message_id
                    if linked is not None:
                        linked_ids.add(linked)

    def _answers_other_reply(self, message_id: str | None, reply_id: str) -> bool:
        if message_id is None:
            return False
        answered = self._answer_of(message_id)
        return answered is not None and answered.reply_id != reply_id

    def _unexecuted_call_ids(self) -> set[str]:
        return set()

    def _tracked_call_ids(self) -> dict[str, list[tuple[str, str | None]]]:
        """Ids the bridge handed in the replies it still tracks.

        Each id maps to the replies that handed it, with the tool message that
        reply's call under it was linked to (`None` if it isn't linked). An id
        another tracked reply handed is ambiguous while that reply's call is
        unlinked. A reply that keeps no handed ids contributes its tracked
        calls' ids (`_link_result_messages` links no other reply's calls while
        it is tracked). Ids from replies dropped by `_MAX_AWAITED_RESULTS`
        aren't known, so a scaffold that copies an
        earlier call and its answer into a later reply can still be taken for
        that reply's call.
        """
        ids: dict[str, list[tuple[str, str | None]]] = {}
        for reply_id, calls in self._awaited_results.items():
            linked = {
                entry.handed.call_id: entry.message_id for entry in calls.values()
            }
            handed_ids = next(iter(calls.values())).handed.handed_ids
            for call_id in handed_ids if handed_ids is not None else linked:
                ids.setdefault(call_id, []).append((reply_id, linked.get(call_id)))
        return ids

    def dispatched_call(self, call: ToolCall) -> DispatchedCall | None:
        """The bridged tool call that `call` makes through a dispatcher, if any.

        Some scaffolds reach every bridged tool through one function whose arguments
        name the target. Approval reviews such a call as the target call, so policies
        match the bridged tool's own name and approvers see (and modify) its own
        arguments. In-process bridges have no bridged tools, so nothing is
        dispatched; `SandboxAgentBridge` overrides this.
        """
        return None

    def reviewed_calls(
        self, call: ToolCall, tools: Sequence[ToolInfo | Tool]
    ) -> ReviewedCalls:
        """The calls approval reviews `call` as.

        Approval must review a call as the tool it will run, so policies match
        that tool's name and approvers see its arguments. Here that is the
        target of a dispatcher call (`dispatched_call`), else the call itself.
        `tools` are the declarations the scaffold made to the model in the
        request that produced `call`. `SandboxAgentBridge` overrides this to
        resolve a call the same way its execution grants do.
        """
        dispatched = self.dispatched_call(call)
        if dispatched is not None:
            return ReviewedCalls([dispatched.target], dispatched.dispatch)
        return ReviewedCalls([call], _unchanged)

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

        Messages in the prefix of a thread the request continues
        (`_align_with_tracked`) take its ids unless a recorded id matches a
        stronger key. Others take the id recorded for their strongest recorded
        key only if that key has one id, no other message of the request has
        the key, and no other message of the request is given the id. Any other
        message gets a new id: which occurrence of repeated content it is can't
        be told, and neither position nor neighbouring messages decide it.

        A tool message after a reply is an answer to that reply, and keeps an
        id only as that reply's answer (`_result_occurrence`). One answering a
        reply given a new id for repeated content gets a new id and no answer
        record, since which reply it answers can't be told; it isn't linked.
        """
        keys = [_message_id_keys(message) for message in messages]
        aligned = self._align_with_tracked(keys)
        key_counts = Counter(key for message_keys in keys for key in set(message_keys))
        unique: list[str | None] = []
        for message_keys in keys:
            key = next((key for key in message_keys if self._message_ids.get(key)), "")
            ids = self._message_ids.get(key, [])
            unique.append(ids[0] if len(ids) == 1 and key_counts[key] == 1 else None)
        reserved = set(aligned.values())
        claimed = Counter([*unique, *reserved])
        used: set[str] = set()

        def recorded_id(index: int) -> str | None:
            id = unique[index]
            return (
                id if id is not None and claimed[id] == 1 and id not in used else None
            )

        def available(message_id: str, index: int) -> bool:
            return message_id not in used and (
                message_id not in reserved or aligned.get(index) == message_id
            )

        recognized: list[str | None] = []
        unattributed: set[str] = set()
        preceding_reply_id: str | None = None
        preceding_reply_key: str | None = None
        preceding_reply_keys: list[str] = []
        preceding_reply_ambiguous: bool | None = None
        preceding_reply_repeated = False
        reply_calls: dict[str, list[ToolCall]] = {}
        for index, (message, message_keys) in enumerate(zip(messages, keys)):
            aligned_id = aligned.get(index)
            message_id = aligned_id
            if aligned_id is None:
                if not (
                    isinstance(message, ChatMessageTool) and preceding_reply_repeated
                ):
                    message_id = recorded_id(index)
            else:
                aligned_keys = self._keys_by_id.get(aligned_id, set())
                aligned_strength = max(
                    (_key_strength(key) for key in message_keys if key in aligned_keys),
                    default=0,
                )
                if aligned_strength < 3:
                    candidate_id = recorded_id(index)
                    if candidate_id is not None:
                        candidate_keys = self._keys_by_id.get(candidate_id, set())
                        candidate_strength = max(
                            (
                                _key_strength(key)
                                for key in message_keys
                                if key in candidate_keys
                            ),
                            default=0,
                        )
                        if candidate_strength > aligned_strength:
                            message_id = candidate_id
            answered: _AnsweredCall | None = None
            linkable = True
            if isinstance(message, ChatMessageTool) and preceding_reply_key is not None:
                answered = _answered_call(
                    preceding_reply_key,
                    reply_calls.get(message.tool_call_id or "", []),
                )
                message_id, linkable = self._result_occurrence(
                    message_keys,
                    message_id,
                    aligned_id is not None and message_id == aligned_id,
                    answered,
                    partial(available, index=index),
                )
            recognized.append(message_id)
            repeated = message_id is None and any(
                key in self._message_ids for key in message_keys
            )
            known = False
            if message_id is None:
                message.id = uuid()
                self._content_by_id[message.id] = content_hash(message)
            else:
                used.add(message_id)
                message.id = self._version_id(message_id, message)
                known = message.id in self._keys_by_id
            used.add(message.id)
            self._record_message_id(message_keys, message.id)
            if answered is not None:
                if not known and not preceding_reply_repeated:
                    if preceding_reply_ambiguous is None:
                        preceding_reply_ambiguous = (
                            preceding_reply_id is not None
                            and self._ambiguous_reply(
                                preceding_reply_id, preceding_reply_keys
                            )
                        )
                    self._record_answer(
                        message.id, answered, preceding_reply_ambiguous, linkable
                    )
                answer = self._answer_of(message.id)
                if answer is None or not answer.linkable:
                    unattributed.add(message.id)
                if answer is not None:
                    self._record_occurrence(message_keys, message.id, answered)
            if isinstance(message, ChatMessageAssistant) and message.tool_calls:
                preceding_reply_id = (
                    self._awaited_reply_id(message_id, message)
                    if message_id is not None
                    else None
                )
                preceding_reply_key = preceding_reply_id or self._edit_root(message.id)
                preceding_reply_keys = message_keys
                preceding_reply_repeated = repeated
                preceding_reply_ambiguous = None
                reply_calls = {}
                for call in message.tool_calls:
                    reply_calls.setdefault(call.id, []).append(call)
        request: list[tuple[str, str]] = [(m.id, m.role) for m in messages if m.id]
        self._latest_request = request
        self._remember_thread(request)
        self._link_result_messages(messages, recognized, unattributed)
        # only after linking, so the request's ownership checks all see the
        # records it started with
        self._drop_answer_records()

    def _result_occurrence(
        self,
        keys: list[str],
        candidate: str | None,
        placed: bool,
        answered: _AnsweredCall,
        available: Callable[[str], bool],
    ) -> "_ResultId":
        """The id of a tool message answering a call of the reply before it.

        The message keeps `candidate` if that was first an answer to this
        reply, or if placement (`placed`) gave it and its first answer isn't
        recorded. Else it takes the id this reply's answer was first given
        under one of its keys. Any other message gets a new id: an equal
        message answering another reply, or whose reply is unknown, may be a
        later execution's result or a copy of the earlier one. A new id isn't
        linkable if it could be such a copy and the call has host executions:
        unless the message equals no earlier answer other than by call id, the
        call's one pending execution must have returned what the earlier
        call's did.
        """
        earlier = self._answer_of(candidate) if candidate is not None else None
        if earlier is not None and earlier.reply_id == answered.reply_id:
            return _ResultId(candidate, True)
        reply_answers = self._reply_answers.get(answered.reply_id)
        for key in keys:
            occurrence = reply_answers.occurrences.get(key) if reply_answers else None
            if occurrence is not None and available(occurrence):
                return _ResultId(occurrence, True)
        if candidate is None:
            return _ResultId(None, True)
        if earlier is None and placed:
            return _ResultId(candidate, True)
        if not any(
            key.startswith(("content:", "loose:"))
            and key in self._keys_by_id.get(candidate, set())
            for key in keys
        ):
            return _ResultId(None, True)
        entries = self._answered_entries(answered)
        if not entries:
            return _ResultId(None, True)
        pending = [entry for entry in entries if not entry.settled]
        return _ResultId(
            None,
            earlier is not None
            and len(pending) == 1
            and earlier.outcomes == {pending[0].outcome},
        )

    def _answered_entries(
        self, answered: _AnsweredCall, identical: bool = False
    ) -> list[_AwaitedResult]:
        """The awaited executions of the call a tool message answers.

        Matched by call id, else (Google re-derives call ids) by function and
        arguments: only a call no other call in its reply is identical to,
        unless `identical`.
        """
        if answered.call is None:
            return []
        call = answered.call

        def is_handed(handed: _HandedCall) -> bool:
            return (call.function, call.arguments) == (
                handed.function,
                handed.arguments,
            )

        entries = self._awaited_results.get(answered.reply_id, {}).values()
        by_id = [entry for entry in entries if entry.handed.call_id == call.id]
        if by_id:
            return [entry for entry in by_id if is_handed(entry.handed)]
        return [
            entry
            for entry in entries
            if (identical or entry.handed.identical == 1) and is_handed(entry.handed)
        ]

    def _edit_root(self, message_id: str) -> str:
        while message_id in self._edit_parent:
            message_id = self._edit_parent[message_id]
        return message_id

    def _answer_of(self, message_id: str) -> _Answer | None:
        return self._answers.get(self._edit_root(message_id))

    def _record_answer(
        self,
        message_id: str,
        answered: _AnsweredCall,
        ambiguous: bool = False,
        linkable: bool = True,
    ) -> None:
        """Record a new tool message as an answer to its reply.

        The record keeps no outcomes when the reply was `ambiguous`: another
        awaited reply matches its copy as strongly (identical replies), so
        recognition may have picked the other's executions, and a later equal
        message must not be taken for a fresh answer on their basis.

        At most `_MAX_ANSWER_RECORDS` records are kept between requests: once a
        request is linked, the oldest replies' are dropped beyond that, so a
        later message equal to one of their answers gets a new id and isn't
        linked. A request's own records may exceed the bound until then.
        """
        if message_id in self._answers:
            return
        self._answers[message_id] = _Answer(
            answered.reply_id,
            frozenset()
            if ambiguous
            else frozenset(
                entry.outcome
                for entry in self._answered_entries(answered, identical=True)
            ),
            linkable,
        )
        self._reply_answer_records(answered.reply_id).message_ids.append(message_id)
        self._answer_records += 1

    def _ambiguous_reply(self, reply_id: str, keys: list[str]) -> bool:
        def strength(original: str) -> int:
            calls = self._awaited_results[original]
            ids = (original, *next(iter(calls.values())).reply_versions)
            return max(
                (
                    _key_strength(key)
                    for id in ids
                    for key in keys
                    if key in self._keys_by_id.get(id, ())
                ),
                default=0,
            )

        recognized = max(strength(reply_id), 1)
        return any(
            other != reply_id and strength(other) >= recognized
            for other in self._awaited_results
        )

    def _record_occurrence(
        self, keys: list[str], message_id: str, answered: _AnsweredCall
    ) -> None:
        first = self._answer_of(message_id)
        if first is None or first.reply_id != answered.reply_id:
            return
        occurrences = self._reply_answer_records(answered.reply_id).occurrences
        for key in keys:
            if key not in occurrences:
                occurrences[key] = message_id
                self._answer_records += 1

    def _reply_answer_records(self, reply_id: str) -> _ReplyAnswers:
        return self._reply_answers.setdefault(reply_id, _ReplyAnswers([], {}))

    def _drop_answer_records(self) -> None:
        while self._answer_records > _MAX_ANSWER_RECORDS:
            _, dropped = self._reply_answers.popitem(last=False)
            for message_id in dropped.message_ids:
                del self._answers[message_id]
            self._answer_records -= len(dropped.message_ids) + len(dropped.occurrences)

    def _version_id(self, message_id: str, message: ChatMessage) -> str:
        """`message_id`, or the id of an edited version if `message`'s content differs.

        Different content never shares an id. A scaffold that sends a message back
        changed (even in whitespace) has edited it: the edit gets an id derived
        from the id it was recognized by and its content, and an edited reply keeps
        the provider state recorded under that id.
        """
        content = content_hash(message)
        if self._content_by_id.setdefault(message_id, content) == content:
            return message_id
        edited_id = edit_id(message_id, content)
        self._content_by_id.setdefault(edited_id, content)
        if isinstance(message, ChatMessageAssistant):
            copy_assistant_internal(message_id, edited_id)
        self._edit_parent[edited_id] = message_id
        return edited_id

    def _align_with_tracked(self, keys: list[list[str]]) -> dict[int, str]:
        """Pair the request's leading messages with a thread it continues.

        A request that starts with the whole tracked thread, the latest
        generation's thread (input and output) or the latest request (a retry)
        may continue it: the scaffold can't invent assistant messages. Older
        threads don't count, since a request after drops can repeat one by
        chance. The longest such thread places the request's messages unless
        another conversation could hold the request's replies with a different
        reply in place of one of its own: one a kept thread holds
        (`_contested`), or one whose threads are no longer kept
        (`_dropped_holds`). That covers retries, rewinds, sliding windows and
        side calls whose replies repeat the thread's.
        """
        for thread in sorted(
            (self._tracked_ids, self._latest_generation, self._latest_request),
            key=len,
            reverse=True,
        ):
            if (
                self._contains(keys, thread)
                and not self._contested(keys, thread)
                and not self._dropped_holds(keys, thread)
            ):
                return {i: message_id for i, (message_id, _) in enumerate(thread)}
        return {}

    def _contested(
        self, keys: list[list[str]], thread: Sequence[tuple[str, str]]
    ) -> bool:
        """Whether a kept thread could hold the request's replies placed by `thread` with another reply in place of one of its own.

        A request comes from a conversation holding its replies in order,
        whatever compaction dropped around them. If the tracked thread or a
        recent request or generation holds the replies `thread` would place in
        more than one way, or as different messages (edits aside), the request
        may continue that conversation instead.
        """
        replies = [
            (keys[i], message_id)
            for i, (message_id, role) in enumerate(thread)
            if role == "assistant"
        ]
        roots = [self._edit_root(message_id) for _, message_id in replies]
        for other in (self._tracked_ids, *self._recent_threads):
            if other is thread:
                continue
            other_ids = [
                message_id for message_id, role in other if role == "assistant"
            ]
            if len(other_ids) < len(replies):
                continue
            first = self._embedding(replies, other_ids)
            if first is not None and (
                first != roots
                or self._embedding(replies[::-1], other_ids[::-1]) != roots[::-1]
            ):
                return True
        return False

    def _remember_thread(self, thread: list[tuple[str, str]]) -> None:
        """Keep `thread` for `_contested`, in place of the kept threads it extends.

        A thread that starts with a kept one holds its replies in the same
        order, so it contests whatever that one would.
        """
        self._keep(thread)
        for kept in [
            kept for kept in self._recent_threads if thread[: len(kept)] == kept
        ]:
            self._recent_threads.remove(kept)
            self._drop(kept)
        self._recent_threads.append(thread)
        if len(self._recent_threads) > _MAX_RECENT_THREADS:
            self._drop(self._recent_threads.popleft())

    def _keep(self, thread: list[tuple[str, str]]) -> None:
        replies = sum(role == "assistant" for _, role in thread)
        for message_id, role in thread:
            if role == "assistant":
                self._held[message_id] += 1
                self._held_replies[message_id] = max(
                    self._held_replies.get(message_id, 0), replies
                )

    def _drop(self, thread: list[tuple[str, str]]) -> None:
        for message_id, role in thread:
            if role != "assistant":
                continue
            self._held[message_id] -= 1
            if self._held[message_id]:
                continue
            del self._held[message_id]
            for key in self._keys_by_id.get(message_id, ()):
                self._dropped_reach[key] = max(
                    self._dropped_reach.get(key, 0), self._held_replies[message_id]
                )

    def _dropped_holds(
        self, keys: list[list[str]], thread: Sequence[tuple[str, str]]
    ) -> bool:
        """Whether a conversation whose threads are no longer kept may hold the replies `thread` would place.

        It may if one of its threads held a reply equal to one of them, which
        no kept thread holds, and at least as many replies.
        """
        replies = [i for i, (_, role) in enumerate(thread) if role == "assistant"]
        return any(
            self._dropped_reach.get(key, 0) >= len(replies)
            for i in replies
            for key in keys[i]
        )

    def _embedding(
        self, replies: list[tuple[list[str], str]], ids: list[str]
    ) -> list[str] | None:
        """The edit roots of the earliest of `ids` holding `replies` in order, or `None` if they don't."""
        remaining = iter(ids)
        matched: list[str] = []
        for message_keys, _ in replies:
            match = next(
                (id for id in remaining if self._strength(message_keys, id)), None
            )
            if match is None:
                return None
            matched.append(self._edit_root(match))
        return matched

    def _contains(
        self, keys: list[list[str]], thread: Sequence[tuple[str, str]]
    ) -> bool:
        return (
            bool(thread)
            and len(keys) >= len(thread)
            and all(self._strength(keys[i], thread[i][0]) for i in range(len(thread)))
        )

    def _strength(self, message_keys: list[str], message_id: str) -> int:
        id_keys = self._keys_by_id.get(message_id, ())
        return max(
            (_key_strength(key) for key in message_keys if key in id_keys),
            default=0,
        )

    def _record_message_id(self, keys: list[str], message_id: str) -> None:
        # `_keys_by_id` mirrors `_message_ids`, so membership is a set lookup
        known = self._keys_by_id.setdefault(message_id, set())
        for key in keys:
            if key not in known:
                self._message_ids.setdefault(key, []).append(message_id)
                known.add(key)

    def _record_transported_reply(
        self, reply: ChatMessageAssistant, transported: list[ChatMessage]
    ) -> None:
        """Recognize `reply` by the form a dialect that re-derives call ids hands back.

        Google derives call ids from function and arguments, so a reply equal to
        an earlier one comes back as that one's copy did; recording its own copy's
        keys lets alignment weigh both.
        """
        if reply.id is None:
            return
        for message in transported:
            if isinstance(message, ChatMessageAssistant):
                self._record_message_id(_message_id_keys(message), reply.id)

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
        for choice in output.choices:
            if choice.message.id is not None:
                self._record_message_id(
                    _message_id_keys(choice.message), choice.message.id
                )
                self._content_by_id.setdefault(
                    choice.message.id, content_hash(choice.message)
                )

        # every choice's thread, since the scaffold may continue any of them;
        # the primary's last, so it stays kept when the window is full
        threads: list[list[tuple[str, str]]] = [
            [(m.id, m.role) for m in [*input, choice.message] if m.id is not None]
            for choice in output.choices
        ]
        for thread in [*threads[1:], threads[0]]:
            self._remember_thread(thread)
        self._latest_generation = threads[0]
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
        tracked: list[tuple[str, str]] = [
            (m.id, m.role) for m in messages if m.id is not None
        ]
        self._keep(tracked)
        self._drop(self._tracked_ids)
        self._tracked_ids = tracked
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

    Scaffolds don't echo message ids. Besides the displayed content, an assistant
    message keeps its tool call ids (every dialect but Google), a tool message
    its call id, and the loose key
    ignores whitespace, JSON key order, call ids and reasoning.
    """
    keys = ["content:" + content_hash(message)]
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        keys.append("calls:" + "\n".join(call.id for call in message.tool_calls))
    if isinstance(message, ChatMessageTool) and message.tool_call_id:
        keys.append(f"result:{message.tool_call_id}")
    keys.append(_loose_message_key(message, message.text))
    return keys


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
                        canonical_tool_arguments(call.arguments),
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
