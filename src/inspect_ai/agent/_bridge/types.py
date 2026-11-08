import json
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
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

from pydantic import BaseModel
from shortuuid import uuid

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.json import jsonable_python
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
    key_counts = Counter(keys)
    id_counts = Counter(call.id for call in calls)
    handed_ids = frozenset(id_counts) if len(calls) <= _MAX_HANDED_IDS else None
    return [
        _HandedCall(
            reply_id,
            position,
            call.id,
            *key,
            key_counts[key],
            handed_ids,
            id_counts[call.id] > 1,
        )
        for position, (call, key) in enumerate(zip(calls, keys))
    ]


class _AwaitedResult(NamedTuple):
    """A host tool call waiting for the tool message that holds its result."""

    handed: _HandedCall
    """The call, as handed to the scaffold."""

    event: "ToolEvent | None"
    """The call's execution, or `None` once settled."""

    outcomes: frozenset[str]
    """Digests of the result and error of each of the call's executions."""

    settled: bool = False
    """Whether the call was linked or found ambiguous, so later results are ignored and later executions left unlinked."""

    message_id: str | None = None
    """Id of the tool message the call was linked to, once settled."""

    reply_versions: tuple[str, ...] = ()
    """Recent edits of the handed reply, kept on one call per pending reply."""


class _CopyCalls(NamedTuple):
    """The calls of a scaffold's copy of a reply."""

    by_id: dict[str, list[tuple[ToolCall, tuple[str, str]]]]
    """Calls with each id, with their function and arguments digest."""

    by_call: dict[tuple[str, str], list[ToolCall]]
    """Calls with each function and arguments digest."""


def _index_copy_calls(calls: Sequence[ToolCall]) -> _CopyCalls:
    copies = _CopyCalls({}, {})
    for call in calls:
        key = (call.function, _arguments_digest(call.arguments))
        copies.by_id.setdefault(call.id, []).append((call, key))
        copies.by_call.setdefault(key, []).append(call)
    return copies


def _copy_calls(
    handed: _HandedCall, copies: _CopyCalls, excluded_ids: Collection[str]
) -> list[ToolCall]:
    """The calls in a scaffold's copy of a reply that may be `handed`.

    None if another call in the reply has its id: an answer under that id
    can't be told apart. Otherwise the one with its id, function and arguments.
    When no copy call has its id (Google re-derives call ids), the ones with
    its function and arguments and an id the bridge knows from no other call
    (`excluded_ids`), but only if `handed` is the
    reply's only call with that function and arguments and its handed ids are
    known. Identical calls can't be told apart, so they are never paired.
    """
    if handed.id_shared:
        return []
    key = (handed.function, handed.arguments)
    same_id = copies.by_id.get(handed.call_id)
    if same_id:
        return [call for call, call_key in same_id if call_key == key]
    if handed.identical != 1 or handed.handed_ids is None:
        return []
    return [c for c in copies.by_call.get(key, []) if c.id not in excluded_ids]


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
    """The reply's call with the message's call id, or `None` if it has none or differing ones, or the id was inferred."""

    function: str | None = None
    """For an inferred call id, the function of the calls the message may answer."""

    calls: int = 0
    """For an inferred call id, how many calls in the reply have `function`."""


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


class _Executions(NamedTuple):
    """The awaited executions of the call a tool message answers (`AgentBridge._executions`)."""

    found: bool

    outcomes: frozenset[str]

    pending: tuple[str, ...]
    """Outcomes of the executions not yet settled."""


class _AwaitedIndex(NamedTuple):
    """A reply's awaited executions by call id, function and call, for one request."""

    by_id: dict[str, list[_AwaitedResult]]

    by_function: dict[str, list[_AwaitedResult]]

    by_call: dict[tuple[str, str], list[_AwaitedResult]]

    executions: dict[tuple[str | int | bool | None, ...], _Executions]


class _ReplyAnswers(NamedTuple):
    """The answer records kept for a reply."""

    message_ids: list[str]
    """Tool messages first sent as its answers (keys of `_answers`)."""

    occurrences: dict[str, str | None]
    """Per message key, the id its answer was first given (`None` once an answer with another id has it too)."""


@dataclass
class _CopiedAnswers:
    """The answer records of the messages recorded under a key (`AgentBridge._copies_answered`)."""

    counted: int = 0
    """How many of the key's ids `outcomes` and `unrecorded` cover."""

    outcomes: Counter[frozenset[str]] = field(default_factory=Counter)
    """Per outcomes, how many of those ids have an answer record with them (see `AgentBridge._copy_keys`)."""

    unrecorded: list[str] = field(default_factory=list)
    """Those ids not yet found with an answer record, or whose record was dropped."""


_MAX_ANSWER_RECORDS = 4096
"""Answer records (`_ReplyAnswers` message ids and occurrences) kept between requests, beyond which the oldest replies' are dropped."""

_MAX_KNOWN_CALL_IDS = 4096
"""Call ids kept in `AgentBridge._known_call_ids`, beyond which the oldest are dropped."""


class _MatchEvidence(BaseModel):
    """The bridge's matching state beyond its recorded ids, kept across a checkpoint resume."""

    threads: list[list[tuple[str, str]]] = [[], []]
    """Each of the threads below once, so one held by several stays one object."""

    recent_threads: list[int] = []

    latest_generation: int = 0

    latest_request: int = 1

    held_replies: dict[str, int] = {}

    dropped_reach: dict[str, int] = {}

    edit_parents: dict[str, str] = {}

    answers: dict[str, _Answer] = {}

    reply_answers: dict[str, _ReplyAnswers] = {}

    known_call_ids: list[str] = []
    """JSON-encoded, so an id holding a lone surrogate is restored unchanged."""


_NO_EVIDENCE = _MatchEvidence()
"""Evidence of a fresh bridge, or of a resume from a checkpoint written before evidence was kept."""

_UNKNOWN_REACH = 2**62
"""Dropped reach of every key a checkpoint without evidence restores: any conversation it knew of may hold a reply, so none is placed."""


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
        evidence = self._cp.track(
            "bridge_match_evidence", self._match_evidence, _NO_EVIDENCE
        )
        self._keys_by_id: dict[str, set[str]] = {}
        self._edit_parent: dict[str, str] = {}
        self._edit_roots: dict[str, str] = {}
        """Per edited id, the id its chain of edits starts from."""
        for edited, parent in evidence.edit_parents.items():
            self._edit_parent[edited] = parent
            self._edit_roots[edited] = self._edit_root(parent)
        self._key_roots: dict[str, str | None] = {}
        """Per key, the edit root of every id recorded under it, or `None` if they have several."""
        restored_keys = list(self._message_ids)
        for key, ids in self._message_ids.items():
            for id in ids:
                self._keys_by_id.setdefault(id, set()).add(key)
                self._record_key_root(key, id)
        self._record_input_message_ids(self._compaction_prefix)
        # the tracked thread's ids, from the checkpoint on resume (which isn't
        # handed back to the scaffold, see above)
        self._tracked_ids: list[tuple[str, str]] = [
            (m.id, m.role) for m in restored_messages if m.id is not None
        ]
        threads = [list(thread) for thread in evidence.threads]
        self._latest_generation = threads[evidence.latest_generation]
        self._latest_request = threads[evidence.latest_request]
        self._recent_threads = deque(threads[i] for i in evidence.recent_threads)
        self._held: Counter[str] = Counter()
        """Kept threads (the tracked thread and recent ones) holding each reply id."""
        self._held_replies = dict(evidence.held_replies)
        self._known_call_ids: dict[str, None] = {}
        """Ids of the calls in the conversation the bridge started with and in every reply it handed, oldest first.

        A resume from a checkpoint without evidence takes those of the
        conversation it restores.
        """
        self._know_call_ids(
            [
                call.id
                for message in restored_messages
                if isinstance(message, ChatMessageAssistant)
                for call in message.tool_calls or []
            ]
            if evidence is _NO_EVIDENCE
            else [json.loads(id) for id in evidence.known_call_ids]
        )
        """Per reply id, the most replies a kept thread holding it had."""
        self._dropped_reach = (
            dict.fromkeys(restored_keys, _UNKNOWN_REACH)
            if evidence is _NO_EVIDENCE
            else dict(evidence.dropped_reach)
        )
        """Per key, the most replies a dropped thread had that held a reply with the key no kept thread holds."""
        for thread in (self._tracked_ids, *self._recent_threads):
            self._keep(thread)
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
        self._executions_memo: dict[str, _AwaitedIndex] = {}
        self._answers = dict(evidence.answers)
        self._reply_answers = OrderedDict(evidence.reply_answers)
        self._answer_records = sum(
            len(answers.message_ids) + len(answers.occurrences)
            for answers in self._reply_answers.values()
        )
        self._copied_answers: dict[str, _CopiedAnswers] = {}
        self._copy_keys: dict[str, set[str]] = {}
        """Per id with an answer record, the keys whose `_CopiedAnswers.outcomes` count it."""
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
        one after the call settled stays unlinked. Every execution's outcome is
        kept, so an answer's record covers whichever one it holds. At most
        `_MAX_AWAITED_RESULTS` calls are tracked; the oldest replies' calls are
        dropped (left unlinked) beyond that.
        """
        outcome = mm3_hash(
            json.dumps(jsonable_python({"result": event.result, "error": event.error}))
        )
        calls = self._awaited_results.setdefault(handed.reply_id, {})
        tracked = calls.get(handed.position)
        if tracked is None:
            calls[handed.position] = _AwaitedResult(handed, event, frozenset([outcome]))
        else:
            calls[handed.position] = tracked._replace(
                event=None, settled=True, outcomes=tracked.outcomes | {outcome}
            )
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
        inferred: Collection[str] = (),
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
        answer without a linkable record (`unattributed`), isn't linked. A call
        whose result has an `inferred` call id settles unlinked. A
        kept id another tracked reply also handed doesn't link while that reply's call is unlinked (`_tracked_call_ids`).
        No call links while another tracked reply keeps no handed ids: any id
        in the copy could be one of that reply's unexecuted calls. A call
        matched by function and arguments doesn't take the id of a call
        proposed but not executed (`_unexecuted_call_ids`), nor of any call the
        bridge handed or started with, including those the scaffold ran itself
        (`_known_call_ids`).

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
            results: dict[str | None, list[ChatMessageTool]] = {}
            for following in messages[index + 1 :]:
                if isinstance(following, ChatMessageAssistant) and following.tool_calls:
                    break
                if isinstance(following, ChatMessageTool):
                    results.setdefault(following.tool_call_id, []).append(following)
            copies = _index_copy_calls(message.tool_calls or [])
            if tracked_ids is None:
                tracked_ids = self._tracked_call_ids()
                excluded_ids = (
                    tracked_ids.keys()
                    | self._unexecuted_call_ids()
                    | self._known_call_ids.keys()
                )
                linked_ids = {
                    linked
                    for ids in tracked_ids.values()
                    for _, linked in ids
                    if linked
                }
            tracked = tracked_ids
            candidates = {
                call_index: _copy_calls(entry.handed, copies, excluded_ids)
                for call_index, entry in awaited.items()
                if not entry.settled
            }
            identified = {
                call_index: same[0]
                for call_index, same in candidates.items()
                if len(same) == 1
            }
            picked = Counter(id(c) for c in identified.values())
            for call_index, copy_call in identified.items():
                if picked[id(copy_call)] != 1 or len(copies.by_id[copy_call.id]) != 1:
                    continue
                matches = results.get(copy_call.id, [])
                if any(r.id in inferred for r in matches):
                    _settle(awaited, call_index, [])
                    continue
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

    def _know_call_ids(self, call_ids: Sequence[str]) -> None:
        for call_id in call_ids:
            self._known_call_ids.pop(call_id, None)
            self._known_call_ids[call_id] = None
        while len(self._known_call_ids) > _MAX_KNOWN_CALL_IDS:
            del self._known_call_ids[next(iter(self._known_call_ids))]

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
        stay in `_known_call_ids` until `_MAX_KNOWN_CALL_IDS` later call ids
        push them out; after that, a scaffold that copies such a call and its
        answer into a later reply can be taken for that reply's call.
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

    def _assign_message_ids(
        self,
        messages: list[ChatMessage],
        inferred_results: Sequence[ChatMessageTool] = (),
    ) -> None:
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
        One before any reply (its reply compacted away) may be another
        execution's equal result, so it keeps only an id placement gives it
        and identifies (`_identifies`), and otherwise gets a new id.

        `inferred_results` are tool messages whose call id the dialect
        inferred rather than read (Google names only a result's function, so
        among calls sharing it the id follows order). Such a message is
        recognized only by its exact content, and not at all when that doesn't
        identify its call (`_unforced_results`). It records no call it answers
        and isn't linked.
        """
        self._executions_memo = {}
        inferred = {id(message) for message in inferred_results}
        inferred_indexes = {i for i, m in enumerate(messages) if id(m) in inferred}
        unforced = _unforced_results(messages, inferred_indexes)
        keys = [
            []
            if index in unforced
            else _message_id_keys(message)[:1]
            if index in inferred_indexes
            else _message_id_keys(message)
            for index, message in enumerate(messages)
        ]
        aligned = self._align_with_tracked(keys, inferred_indexes)
        reserved = {self._edit_root(id) for id in aligned.values()}
        for index in inferred_indexes & aligned.keys():
            if not self._strength(keys[index], aligned[index]):
                del aligned[index]
        key_counts = Counter(key for message_keys in keys for key in set(message_keys))
        unique: list[str | None] = []
        for message, message_keys in zip(messages, keys):
            key = next((key for key in message_keys if self._message_ids.get(key)), "")
            named = self._named_id(key) if key_counts[key] == 1 else None
            if named is not None and not self._sole_source(
                message, message_keys, named
            ):
                named = None
            unique.append(named)
        self._drop_contradicted_placements(keys, unique, aligned)
        claimed = Counter(
            self._edit_root(id) for id in [*unique, *aligned.values()] if id is not None
        )
        used: set[str] = set()
        """Edit roots of the ids given so far."""

        def recorded_id(index: int) -> str | None:
            id = unique[index]
            if id is None:
                return None
            root = self._edit_root(id)
            return id if claimed[root] == 1 and root not in used else None

        def available(message_id: str, index: int) -> bool:
            root = self._edit_root(message_id)
            return root not in used and (
                root not in reserved or self._edit_root(aligned.get(index, "")) == root
            )

        recognized: list[str | None] = []
        unattributed: set[str] = set()
        preceding_reply_id: str | None = None
        preceding_reply_key: str | None = None
        preceding_reply_keys: list[str] = []
        preceding_reply_rivals: list[str] | None = None
        preceding_reply_repeated = False
        reply_calls: dict[str, list[ToolCall]] = {}
        reply_answered: dict[str, _AnsweredCall] = {}
        reply_functions: Counter[str] = Counter()
        for index, (message, message_keys) in enumerate(zip(messages, keys)):
            aligned_id = aligned.get(index)
            message_id = aligned_id
            if isinstance(message, ChatMessageTool) and preceding_reply_key is None:
                if aligned_id is not None and not self._identifies(
                    message_keys, aligned_id, exact=False
                ):
                    message_id = None
            elif aligned_id is None:
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
                call_id = message.tool_call_id or ""
                if index in inferred_indexes:
                    answered = _AnsweredCall(
                        preceding_reply_key,
                        None,
                        message.function,
                        reply_functions[message.function or ""],
                    )
                else:
                    answered = reply_answered.get(call_id)
                    if answered is None:
                        answered = _answered_call(
                            preceding_reply_key, reply_calls.get(call_id, [])
                        )
                        reply_answered[call_id] = answered
                message_id, linkable = self._result_occurrence(
                    message_keys,
                    message_id,
                    aligned_id is not None and message_id == aligned_id,
                    answered,
                    partial(available, index=index),
                    len(reply_calls.get(call_id, [])) > 1,
                )
                linkable = linkable and index not in inferred_indexes
            recognized.append(message_id)
            repeated = message_id is None and any(
                key in self._message_ids for key in message_keys
            )
            known = False
            if message_id is None:
                message.id = uuid()
                self._content_by_id[message.id] = content_hash(message)
            else:
                message.id = self._version_id(message_id, message)
                known = message.id in self._keys_by_id
            used.add(self._edit_root(message.id))
            self._record_message_id(message_keys, message.id)
            if answered is not None:
                if not known and not preceding_reply_repeated:
                    if preceding_reply_rivals is None:
                        preceding_reply_rivals = (
                            self._rival_replies(
                                preceding_reply_id, preceding_reply_keys
                            )
                            if preceding_reply_id is not None
                            else []
                        )
                    self._record_answer(
                        message.id, answered, preceding_reply_rivals, linkable
                    )
                answer = self._answer_of(message.id)
                if answer is None or not answer.linkable or index in inferred_indexes:
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
                preceding_reply_rivals = None
                reply_calls = {}
                reply_answered = {}
                for call in message.tool_calls:
                    reply_calls.setdefault(call.id, []).append(call)
                reply_functions = Counter(call.function for call in message.tool_calls)
        request: list[tuple[str, str]] = [(m.id, m.role) for m in messages if m.id]
        self._latest_request = request
        self._remember_thread(request)
        self._link_result_messages(
            messages,
            recognized,
            unattributed,
            {
                message_id
                for index in inferred_indexes
                if (message_id := messages[index].id) is not None
            },
        )
        # only after linking, so the request's ownership checks all see the
        # records it started with
        self._drop_answer_records()

    def _drop_contradicted_placements(
        self, keys: list[list[str]], unique: list[str | None], aligned: dict[int, str]
    ) -> None:
        """Drop placements a placed message's exact content contradicts.

        A message whose content key names one recorded message, which no other
        message of the request is recognized as, is that message's unchanged
        copy. Placed elsewhere by weaker keys (a call id calls can share), it
        keeps its own id, and the message placed as the one it copies doesn't
        take that id. A copy outside the placed messages leaves placement as
        it is: it may be a new message equal to a placed one before an edit.
        """
        roots = [self._edit_root(id) if id is not None else None for id in unique]
        counts = Counter(root for root in roots if root is not None)
        contradicted: set[str] = set()
        for index, message_id in list(aligned.items()):
            id, root = unique[index], roots[index]
            if (
                id is not None
                and root is not None
                and counts[root] == 1
                and root != self._edit_root(message_id)
                and self._strength(keys[index], id) == 3
            ):
                contradicted.add(root)
                del aligned[index]
        for index, message_id in list(aligned.items()):
            if self._edit_root(message_id) in contradicted:
                del aligned[index]

    def _result_occurrence(
        self,
        keys: list[str],
        candidate: str | None,
        placed: bool,
        answered: _AnsweredCall,
        available: Callable[[str], bool],
        shared_call_id: bool,
    ) -> "_ResultId":
        """The id of a tool message answering a call of the reply before it.

        The message keeps `candidate` if that was first an answer to this
        reply, or if placement (`placed`) gave it and its first answer isn't
        recorded. Else it takes the id this reply's answer was first given
        under one of its keys, unless answers with other ids have that key or
        the message's content or loose key: which of them it is can't be told.
        Any other message gets a new id: an equal message answering another
        reply, or whose reply is unknown, may be a later execution's result or
        a copy of the earlier one (`_new_result_linkable`).

        Position doesn't say which answer a placed message is: then only a key
        that names no other message does (`_identifies`). Under a call id the
        reply's calls share (`shared_call_id`), a sibling's result may not be
        recorded, so only the exact content says which call's it is.
        """
        if (
            candidate is not None
            and (placed or shared_call_id)
            and not self._identifies(keys, candidate, exact=shared_call_id)
        ):
            candidate = None
        earlier = self._answer_of(candidate) if candidate is not None else None
        if earlier is not None and earlier.reply_id == answered.reply_id:
            return _ResultId(candidate, True)
        reply_answers = self._reply_answers.get(answered.reply_id)
        occurrences = reply_answers.occurrences if reply_answers else {}
        if not any(
            key in occurrences and occurrences[key] is None and _key_strength(key) != 2
            for key in keys
        ):
            for key in keys:
                if shared_call_id and _key_strength(key) != 3:
                    continue
                occurrence = occurrences.get(key)
                if occurrence is not None and available(occurrence):
                    return _ResultId(occurrence, True)
        if candidate is not None and earlier is None and placed:
            return _ResultId(candidate, True)
        return _ResultId(None, self._new_result_linkable(keys, answered))

    def _identifies(self, keys: list[str], message_id: str, exact: bool) -> bool:
        """Whether a message with `keys` is an unchanged copy of `message_id`, or (unless `exact`) an edit of no other recorded message.

        An edit is told by a key that names `message_id` and no other recorded
        message.
        """
        root = self._edit_root(message_id)
        id_keys = self._keys_by_id.get(message_id, ())
        return any(
            (_key_strength(key) == 3 and key in id_keys)
            or (not exact and self._key_roots.get(key) == root)
            for key in keys
        )

    def _new_result_linkable(self, keys: list[str], answered: _AnsweredCall) -> bool:
        """Whether a tool message given a new id may be linked to its call's host execution.

        The message may be a copy of any message recorded under its content or
        loose key, whether or not recognition named one. Unless there is none,
        or the call has no host executions, each must be an answer whose call's
        executions returned what the call's one pending execution did.
        """
        executions = self._executions(answered)
        if not executions.found:
            return True
        copy_keys = [key for key in keys if key.startswith(("content:", "loose:"))]
        if not any(self._message_ids.get(key) for key in copy_keys):
            return True
        if len(executions.pending) != 1:
            return False
        pending = frozenset(executions.pending)
        return all(self._copies_answered(key, pending) for key in copy_keys)

    def _copies_answered(self, key: str, outcomes: frozenset[str]) -> bool:
        """Whether every message recorded under `key` has an answer record with `outcomes`.

        Each message's own record, not its edit root's: an edit sent after the
        call ran again may hold that execution's result. An edit without a
        record of its own doesn't count as an answer.

        Kept per key and updated as ids are recorded and records dropped, so
        repeated results don't each rescan the ids recorded under their keys.
        """
        ids = self._message_ids.get(key, [])
        copied = self._copied_answers.setdefault(key, _CopiedAnswers())
        copied.unrecorded.extend(ids[copied.counted :])
        copied.counted = len(ids)
        while copied.unrecorded:
            message_id = copied.unrecorded[-1]
            answer = self._answers.get(message_id)
            if answer is None:
                return False
            copied.unrecorded.pop()
            counted = self._copy_keys.setdefault(message_id, set())
            if key not in counted:
                counted.add(key)
                copied.outcomes[answer.outcomes] += 1
        return all(recorded == outcomes for recorded in copied.outcomes)

    def _executions(
        self, answered: _AnsweredCall, identical: bool = False
    ) -> "_Executions":
        """The awaited executions of the call a tool message answers.

        Matched by call id, else (Google re-derives call ids) by function and
        arguments: only a call no other call in its reply is identical to,
        unless `identical`. For an inferred call id, every call with the
        message's function, or none unless each such call was executed.
        Memoized for the request, so a reply's answers index its calls once.
        """
        index = self._executions_memo.get(answered.reply_id)
        if index is None:
            index = _AwaitedIndex({}, {}, {}, {})
            for entry in self._awaited_results.get(answered.reply_id, {}).values():
                handed = entry.handed
                index.by_id.setdefault(handed.call_id, []).append(entry)
                index.by_function.setdefault(handed.function, []).append(entry)
                index.by_call.setdefault(
                    (handed.function, handed.arguments), []
                ).append(entry)
            self._executions_memo[answered.reply_id] = index
        call = answered.call
        memo_key: tuple[str | int | bool | None, ...]
        if call is None:
            memo_key = ("function", answered.function, answered.calls)
        elif call.id in index.by_id:
            memo_key = ("id", call.id, call.function, call.arguments)
        else:
            memo_key = ("call", call.function, call.arguments, identical)
        executions = index.executions.get(memo_key)
        if executions is not None:
            return executions
        if call is None:
            entries = index.by_function.get(answered.function or "", [])
            if answered.function is None or len(entries) != answered.calls:
                entries = []
        elif call.id in index.by_id:
            entries = [
                entry
                for entry in index.by_id[call.id]
                if (entry.handed.function, entry.handed.arguments)
                == (call.function, call.arguments)
            ]
        else:
            entries = [
                entry
                for entry in index.by_call.get((call.function, call.arguments), [])
                if identical or entry.handed.identical == 1
            ]
        executions = _Executions(
            bool(entries),
            frozenset().union(*(entry.outcomes for entry in entries)),
            tuple(
                outcome
                for entry in entries
                if not entry.settled
                for outcome in entry.outcomes
            ),
        )
        index.executions[memo_key] = executions
        return executions

    def _edit_root(self, message_id: str) -> str:
        return self._edit_roots.get(message_id, message_id)

    def _answer_of(self, message_id: str) -> _Answer | None:
        return self._answers.get(self._edit_root(message_id))

    def _record_answer(
        self,
        message_id: str,
        answered: _AnsweredCall,
        rivals: Collection[str] = (),
        linkable: bool = True,
    ) -> None:
        """Record a new tool message as an answer to its reply.

        `rivals` are other awaited replies that match the reply's copy as
        strongly (identical replies), so recognition may have picked the wrong
        one's executions. The record keeps no outcomes unless the call's
        executions in each rival returned the same outcomes: a later equal
        message must not be taken for a fresh answer on the basis of the
        wrong executions.

        At most `_MAX_ANSWER_RECORDS` records are kept between requests: once a
        request is linked, the oldest replies' are dropped beyond that, so a
        later message equal to one of their answers gets a new id and isn't
        linked. A request's own records may exceed the bound until then.
        """
        if message_id in self._answers:
            return
        outcomes = self._executions(answered, identical=True).outcomes
        if any(
            self._executions(answered._replace(reply_id=rival), identical=True).outcomes
            != outcomes
            for rival in rivals
        ):
            outcomes = frozenset()
        self._answers[message_id] = _Answer(answered.reply_id, outcomes, linkable)
        self._reply_answer_records(answered.reply_id).message_ids.append(message_id)
        self._answer_records += 1

    def _rival_replies(self, reply_id: str, keys: list[str]) -> list[str]:
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
        return [
            other
            for other in self._awaited_results
            if other != reply_id and strength(other) >= recognized
        ]

    def _record_occurrence(
        self, keys: list[str], message_id: str, answered: _AnsweredCall
    ) -> None:
        first = self._answer_of(message_id)
        if first is None or first.reply_id != answered.reply_id:
            return
        occurrences = self._reply_answer_records(answered.reply_id).occurrences
        root = self._edit_root(message_id)
        for key in keys:
            if key not in occurrences:
                occurrences[key] = message_id
                self._answer_records += 1
            elif (first_id := occurrences[key]) and self._edit_root(first_id) != root:
                occurrences[key] = None

    def _reply_answer_records(self, reply_id: str) -> _ReplyAnswers:
        return self._reply_answers.setdefault(reply_id, _ReplyAnswers([], {}))

    def _drop_answer_records(self) -> None:
        while self._answer_records > _MAX_ANSWER_RECORDS:
            _, dropped = self._reply_answers.popitem(last=False)
            for message_id in dropped.message_ids:
                answer = self._answers.pop(message_id)
                for key in self._copy_keys.pop(message_id, ()):
                    copied = self._copied_answers[key]
                    copied.outcomes[answer.outcomes] -= 1
                    if not copied.outcomes[answer.outcomes]:
                        del copied.outcomes[answer.outcomes]
                    copied.unrecorded.append(message_id)
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
        self._edit_roots[edited_id] = self._edit_root(message_id)
        return edited_id

    def _align_with_tracked(
        self, keys: list[list[str]], wildcards: Collection[int] = ()
    ) -> dict[int, str]:
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
        side calls whose replies repeat the thread's. A tool message at a
        `wildcards` index (a result whose call id was inferred) fits any tool
        message of the thread.
        """
        for thread in sorted(
            (self._tracked_ids, self._latest_generation, self._latest_request),
            key=len,
            reverse=True,
        ):
            if (
                self._contains(keys, thread, wildcards)
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

    def _match_evidence(self) -> _MatchEvidence:
        threads: dict[int, tuple[int, list[tuple[str, str]]]] = {}

        def index(thread: list[tuple[str, str]]) -> int:
            return threads.setdefault(id(thread), (len(threads), thread))[0]

        recent = [index(thread) for thread in self._recent_threads]
        generation = index(self._latest_generation)
        request = index(self._latest_request)
        return _MatchEvidence(
            threads=[thread for _, thread in threads.values()],
            recent_threads=recent,
            latest_generation=generation,
            latest_request=request,
            held_replies=self._held_replies,
            dropped_reach=self._dropped_reach,
            edit_parents=self._edit_parent,
            answers=self._answers,
            reply_answers=self._reply_answers,
            known_call_ids=[json.dumps(id) for id in self._known_call_ids],
        )

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
            replies = self._held_replies.pop(message_id)
            for key in self._keys_by_id.get(message_id, ()):
                self._dropped_reach[key] = max(self._dropped_reach.get(key, 0), replies)

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
        self,
        keys: list[list[str]],
        thread: Sequence[tuple[str, str]],
        wildcards: Collection[int],
    ) -> bool:
        return (
            bool(thread)
            and len(keys) >= len(thread)
            and all(
                (i in wildcards and role == "tool")
                or self._strength(keys[i], message_id)
                for i, (message_id, role) in enumerate(thread)
            )
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
                self._record_key_root(key, message_id)

    def _record_key_root(self, key: str, message_id: str) -> None:
        root = self._edit_root(message_id)
        if self._key_roots.setdefault(key, root) != root:
            self._key_roots[key] = None

    def _named_id(self, key: str) -> str | None:
        """The id of the one message recorded under `key` (its edits count as it), if there is one."""
        root = self._key_roots.get(key)
        if root is None:
            return None
        ids = self._message_ids[key]
        return ids[0] if len(ids) == 1 else root

    def _sole_source(
        self, message: ChatMessage, message_keys: list[str], message_id: str
    ) -> bool:
        """Whether `message_id` is the only recorded message `message` could be an edit of.

        A scaffold may edit a message in any way its loose key ignores, so
        another message recorded under that key could have become `message`,
        however strong the key `message_id` was recognized by. Only call ids
        no other message was recorded with show which one it was: an edit
        doesn't give a message another one's call ids.
        """
        root = self._edit_root(message_id)
        if any(
            _key_strength(key) == 2 and self._key_roots.get(key) == root
            for key in message_keys
        ):
            return True
        loose = _message_id_keys(message)[-1]
        return self._key_roots.get(loose, root) == root

    def _record_transported_reply(
        self, reply: ChatMessageAssistant, transported: list[ChatMessage]
    ) -> None:
        """Recognize `reply` by the form its dialect hands it back in.

        A dialect's wire form can drop parts of a reply (Responses and
        Anthropic an empty text, Google call ids), so a reply equal to an
        earlier one in that form comes back as that one's copy did. Recording
        each reply's form means a key the copies share names both replies.
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

    async def _track_state(
        self,
        input: list[ChatMessage],
        output: ModelOutput,
        transported: Sequence[list[ChatMessage]],
    ) -> None:
        """Track agent state by observing generations made through the bridge.

        `transported` holds each choice handed back to the scaffold in its
        dialect's wire form (see `_record_transported_reply`). It is recorded
        before the checkpointer tick this method ends with, so a checkpoint
        has every form of the generation.

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
        for choice, form in zip(output.choices, transported):
            self._record_transported_reply(choice.message, form)
        self._know_call_ids(
            [
                call.id
                for choice in output.choices
                for call in choice.message.tool_calls or []
            ]
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


def _unforced_results(
    messages: list[ChatMessage], inferred: Collection[int]
) -> set[int]:
    """Indexes of `inferred` results that don't identify their call.

    One doesn't when another result of its function after the same reply has
    its content but for the call id, or when not every call of the reply with
    that function has a result in the request.
    """
    groups: dict[tuple[int, str | None], dict[str, list[int]]] = {}
    calls: dict[tuple[int, str | None], int] = {}
    reply = -1
    functions: Counter[str] = Counter()
    for index, message in enumerate(messages):
        if isinstance(message, ChatMessageAssistant) and message.tool_calls:
            reply = index
            functions = Counter(call.function for call in message.tool_calls)
        elif index in inferred and isinstance(message, ChatMessageTool):
            group = (reply, message.function)
            content = content_hash(message.model_copy(update={"tool_call_id": None}))
            groups.setdefault(group, {}).setdefault(content, []).append(index)
            calls[group] = functions[message.function or ""]
    unforced: set[int] = set()
    for group, by_content in groups.items():
        complete = sum(map(len, by_content.values())) == calls[group]
        for indexes in by_content.values():
            if len(indexes) > 1 or not complete:
                unforced.update(indexes)
    return unforced


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
        keys.append("calls:" + json.dumps([call.id for call in message.tool_calls]))
    if isinstance(message, ChatMessageTool) and message.tool_call_id:
        keys.append("result:" + json.dumps(message.tool_call_id))
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
                    else c.model_dump(exclude_none=True)
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
