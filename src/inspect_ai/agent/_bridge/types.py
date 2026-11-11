import json
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import IntEnum
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    NamedTuple,
    NoReturn,
    Sequence,
)

from pydantic import BaseModel
from shortuuid import uuid

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
    shown_text,
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

_MAX_RECENT_THREADS = 16
"""Recent requests and generations kept, each in place of the kept ones it extends, whose replies can contest a thread's placement (see `_contested`)."""

_UNKNOWN_REACH = 2**62
"""Dropped reach of every content a bridge resumed from a checkpoint without placement state knew: a conversation it can't see may hold any such reply, so none is placed."""


class _TrackingState(BaseModel):
    """The state `AgentBridge._track_state` picks the tracked thread by, as a checkpoint keeps it."""

    fps: list[tuple[str, str]]

    calls: int

    descends: int | None = None

    candidate_fps: list[tuple[str, str]] | None = None

    last_message_count: int


class _PlacementState(BaseModel):
    """The threads a bridge places requests by (`AgentBridge._align_with_tracked`), as a checkpoint keeps them."""

    threads: list[list[tuple[str, str]]] = [[], []]
    """Each of the threads below once, so one held by several stays one object."""

    recent_threads: list[int] = []

    latest_generation: int = 0

    latest_request: int = 1

    forms: dict[str, list[str]] = {}
    """Forms of the ids in the tracked thread and the threads above, and of every other id in `bridge_message_ids` with a form besides its content (`bridge_message_content`)."""

    edit_roots: dict[str, str] = {}
    """Edit roots of every edited id (of the ids in the threads above, in a checkpoint written before all were kept)."""

    dropped_reach: dict[str, int] = {}

    held_replies: dict[str, int] | None = None
    """Per reply id the kept threads hold, the most replies a kept thread holding it had, also one no longer kept. `None` in a checkpoint written before it was kept: the resumed bridge counts the threads it restores."""

    tracking: _TrackingState | None = None
    """`None` before the first generation, or from a checkpoint written before it was kept: the resumed bridge then tracks the first generation it sees."""


_NO_PLACEMENT = _PlacementState()
"""Placement state of a fresh bridge, or of a resume from a checkpoint written before it was kept."""


@dataclass(eq=False)
class _HandedReply:
    """A reply handed to the scaffold, shared by its calls (`_HandedCall`)."""

    id: str
    """Id of the reply."""

    calls: int
    """How many calls the reply has."""

    handed_at: int
    """How many requests the bridge had given ids (`AgentBridge._requests`) when it handed the reply out."""


class _HandedCall(NamedTuple):
    """A call in a reply handed to the scaffold."""

    reply: _HandedReply
    """The reply."""

    position: int
    """The call's index in the reply."""


@dataclass
class _AwaitedReply:
    """A reply handed to the scaffold whose executed calls await their result messages."""

    calls: int
    """How many calls the reply has."""

    handed_at: int
    """`_HandedReply.handed_at`."""

    events: dict[int, "ToolEvent | None"] = field(default_factory=dict)
    """Per executed call's position, its execution, or `None` once the call is settled (linked, or left unlinked)."""


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
        self._resumed_state: tuple[list[ChatMessage], ModelOutput] | None = None
        """The restored tracked thread and output, until the first generation after a resume that restored its tracking applies them (`_track_state`)."""
        restored_messages = self._cp.track(
            "bridge_messages",
            lambda: self._tracked_state()[0],
            state.messages,
            value_type=list[ChatMessage],
        )
        restored_output = self._cp.track(
            "bridge_output", lambda: self._tracked_state()[1], state.output
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
        placement = self._cp.track(
            "bridge_placement", self._placement_state, _NO_PLACEMENT
        )
        self._recorded = {
            (key, id) for key, ids in self._message_ids.items() for id in ids
        }
        """The (key, id) pairs in `_message_ids`."""
        self._forms: dict[str, set[str]] = {
            id: set(forms) for id, forms in placement.forms.items()
        }
        """Per id, the `content_hash` of each form a message with it was sent or handed in."""
        self._edit_roots = dict(placement.edit_roots)
        """Per edited id, the id its chain of edits starts from."""
        self._dropped_reach = dict(placement.dropped_reach)
        """Per content hash, the most replies a dropped thread had that held a reply with it no kept thread holds."""
        if placement is _NO_PLACEMENT and self._cp.attempt != "initial":
            # a checkpoint without the threads: a conversation the resumed bridge
            # can't see may hold any reply it knew of
            self._dropped_reach = dict.fromkeys(
                self._content_by_id.values(), _UNKNOWN_REACH
            )
        self._ids_with_content = Counter(self._content_by_id.values())
        """Per `content_hash`, how many ids have it (`_content_by_id`)."""
        self._record_forms(self._compaction_prefix)
        # the tracked thread's ids, from the checkpoint on resume (which isn't
        # handed back to the scaffold, see above)
        self._tracked_ids: list[tuple[str, str]] = [
            (m.id, m.role) for m in restored_messages if m.id is not None
        ]
        threads = [list(thread) for thread in placement.threads]
        self._latest_generation = threads[placement.latest_generation]
        self._latest_request = threads[placement.latest_request]
        self._recent_threads = deque(threads[i] for i in placement.recent_threads)
        self._held: Counter[str] = Counter()
        """Kept threads (`_kept_threads`) holding each reply id, counting a thread once per role it is kept in."""
        self._held_replies: dict[str, int] = {}
        """Per reply id kept threads hold, the most replies a thread held it in while it stayed held, also a thread no longer kept."""
        for thread in (
            self._tracked_ids,
            self._latest_generation,
            self._latest_request,
            *self._recent_threads,
        ):
            self._keep(thread)
        for message_id, replies in (placement.held_replies or {}).items():
            if message_id in self._held_replies:
                self._held_replies[message_id] = max(
                    self._held_replies[message_id], replies
                )
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
        self._initial_texts = [shown_text(m.content).strip() for m in initial_messages]
        self._tracked_fps: list[_MessageFingerprint] | None = None
        self._tracked_calls = 0
        self._tracked_descends: _Descent | None = None
        self._candidate_fps: list[_MessageFingerprint] | None = None
        if placement.tracking is not None and self._cp.attempt == "resume":
            self._restore_tracking(placement.tracking)
            self._resumed_state = (restored_messages, restored_output)
        self._pending_operator = 0
        self._awaited_results: dict[str, _AwaitedReply] = {}
        """Per reply handed to the scaffold, its executed calls awaiting their results."""
        self._requests = 0
        """How many requests the bridge has given ids (`_assign_message_ids`)."""
        self._result_sent_in: dict[str, int] = {}
        """Per `content_hash` of a tool message, the number of the latest request that sent it.

        Like `_awaited_results`, not checkpointed: a resumed bridge links only replies it hands out itself.
        """
        self._unlinked_replies: set[str] = set()
        """Ids of handed replies none of whose executions links (`_unlink`)."""
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

    def _handed_calls(
        self, reply_id: str, calls: Sequence[ToolCall]
    ) -> list[_HandedCall]:
        """The calls of a reply handed to the scaffold, for `_await_result_message`.

        A reply whose id the bridge already knows (a cached generation hands
        out an earlier reply again, also one handed out before a checkpoint
        the bridge resumed from) is unlinked (`_unlink`): its calls can run
        once per hand-out, and the bridge may no longer track the executions
        of an earlier one. Called before `_track_state` records the reply, so
        a first hand-out's id is not yet known.
        """
        if reply_id in self._content_by_id:
            self._unlink(reply_id)
        reply = _HandedReply(reply_id, len(calls), self._requests)
        return [_HandedCall(reply, position) for position in range(len(calls))]

    def _await_result_message(
        self, handed: _HandedCall, event: "ToolEvent", linkable: bool = True
    ) -> None:
        """Set `event.message_id` when the scaffold first sends the result of `handed`.

        The result reaches the bridge only when the scaffold sends it back in a
        later request (`_link_result_messages`). A second execution of the call,
        or one that may have run another call (not `linkable`), settles it
        unlinked, since which execution a result holds is unknown; one after
        the call settled, or of a reply unlinked before it completed, leaves it
        as it is. At most
        `_MAX_AWAITED_RESULTS` calls are tracked; beyond that the oldest
        replies are dropped and their ids recorded in `_unlinked_replies`, as
        `_unlink` records them, since the bridge no longer holds evidence of
        their executions. The caller passes `linkable=False` for any execution
        after a call's first, and a reply handed out again is unlinked
        (`_handed_calls`), so this is a second guard; it also leaves unlinked
        a call of theirs first executed after the drop.
        """
        reply = self._awaited_results.setdefault(
            handed.reply.id, _AwaitedReply(handed.reply.calls, handed.reply.handed_at)
        )
        executed = handed.position in reply.events
        reply.events[handed.position] = (
            event
            if linkable
            and not executed
            and self._edit_root(handed.reply.id) not in self._unlinked_replies
            else None
        )
        tracked = sum(len(reply.events) for reply in self._awaited_results.values())
        while tracked > _MAX_AWAITED_RESULTS:
            oldest = next(iter(self._awaited_results))
            tracked -= len(self._awaited_results.pop(oldest).events)
            self._unlinked_replies.add(self._edit_root(oldest))

    def _link_result_messages(
        self,
        messages: list[ChatMessage],
        placed: dict[int, str],
        fresh: set[int],
        inferred: set[int],
        sent_in: dict[int, int],
    ) -> None:
        """Link awaited host tool executions to their result messages in a request.

        A call links only when its result is certain: the reply holding it was
        placed (`_align_with_tracked`) under the id it was handed with, the call
        ran once, its id is unique in the reply and no other call of the reply
        has its function and arguments (an execution of either may have taken
        the other's grant), and exactly one tool message
        answers it before the next assistant message with tool calls. That
        message must also be new in this request (`fresh`), and no earlier
        request since the reply was handed out may have sent a message with
        its content (`sent_in`, per tool message the latest earlier request
        that did), so it was first sent after the execution completed: a
        message sent before, or equal to one sent before, may hold another
        result. Any other result settles
        the call unlinked, as does a result whose call id the dialect inferred
        from order (`inferred`). A call with no result yet keeps waiting.
        """
        from inspect_ai.log._transcript import transcript

        if not self._awaited_results:
            return
        for index, thread_id in placed.items():
            message = messages[index]
            reply = self._awaited_results.get(self._edit_root(thread_id))
            if (
                reply is None
                or not isinstance(message, ChatMessageAssistant)
                or not message.tool_calls
            ):
                continue
            calls = message.tool_calls
            results: dict[str, list[int]] = {}
            for following in range(index + 1, len(messages)):
                result = messages[following]
                if isinstance(result, ChatMessageAssistant) and result.tool_calls:
                    break
                if isinstance(result, ChatMessageTool):
                    results.setdefault(result.tool_call_id or "", []).append(following)
            call_ids = Counter(call.id for call in calls)
            identical = Counter(map(_call_key, calls))
            for position, event in reply.events.items():
                if event is None:
                    continue
                call = calls[position] if len(calls) == reply.calls else None
                if (
                    call is None
                    or call_ids[call.id] != 1
                    or identical[_call_key(call)] != 1
                ):
                    reply.events[position] = None
                    continue
                answers = results.get(call.id)
                if not answers:
                    continue
                reply.events[position] = None
                if (
                    len(answers) == 1
                    and answers[0] in fresh
                    and answers[0] not in inferred
                    and sent_in.get(answers[0], 0) <= reply.handed_at
                ):
                    event.message_id = messages[answers[0]].id
                    transcript()._event_updated(event)

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
        named_results: bool = False,
    ) -> None:
        """Give each message of a request the id the bridge knows it by.

        Messages in the prefix of a thread the request continues unchanged
        (`_align_with_tracked`) take its ids. Every other message gets the id
        the bridge has always given a bridged message (`_unplaced_id`): the id
        an equal message had in an earlier request, placed or not. An
        ambiguous message so keeps its id from request to request, but may
        share it with an equal message.

        `inferred_results` are tool messages whose call id the dialect
        inferred rather than read (Google names only a result's function, so
        among calls sharing it the id follows order). They aren't linked.

        A message is new in the request (`fresh`, which a linked result must
        be) when it takes a new id and it is the n-th message of the request
        with its content while fewer than n ids had that content before. The
        id alone doesn't show that: it is recorded under the message's JSON,
        which differs between forms of one content (string content and a
        list of one text part, or other metadata).

        With `named_results` (Google), a result names its function rather
        than its call, and the call id the dialect gives it depends on the
        call's position in its turn. Whether an equal result was sent before
        (`_link_result_messages`) is then judged by the function and
        arguments of the call it answers (`_named_result_key`).
        """
        self._requests += 1
        contents = [content_hash(message) for message in messages]
        known = {content: self._ids_with_content[content] for content in contents}
        sent: Counter[str] = Counter()
        placed = self._align_with_tracked(contents)
        used: set[str] = set()
        cursors: dict[str, int] = {}
        fresh: set[int] = set()
        for index, (message, content) in enumerate(zip(messages, contents)):
            key = _unplaced_key(message)
            thread_id = placed.get(index)
            sent[content] += 1
            if thread_id is not None:
                message.id = self._version_id(thread_id, message, content)
            else:
                message.id, new = self._unplaced_id(key, used, cursors)
                if not new:
                    self._unlink(message.id)
                elif sent[content] > known[content]:
                    fresh.add(index)
            used.add(message.id)
            self._record_form(message.id, content)
            if (key, message.id) not in self._recorded:
                self._recorded.add((key, message.id))
                self._message_ids.setdefault(key, []).append(message.id)
        request: list[tuple[str, str]] = [(m.id, m.role) for m in messages if m.id]
        self._latest_request = self._replace_kept(self._latest_request, request)
        self._remember_thread(request)
        inferred = {id(message) for message in inferred_results}
        calls = (
            {
                call.id: call
                for message in messages
                if isinstance(message, ChatMessageAssistant)
                for call in message.tool_calls or []
            }
            if named_results
            else {}
        )
        keys = {
            index: _named_result_key(message, calls.get(message.tool_call_id or ""))
            if named_results
            else contents[index]
            for index, message in enumerate(messages)
            if isinstance(message, ChatMessageTool)
        }
        sent_in = {
            index: self._result_sent_in[key]
            for index, key in keys.items()
            if key in self._result_sent_in
        }
        self._link_result_messages(
            messages,
            placed,
            fresh,
            {
                index
                for index, message in enumerate(messages)
                if id(message) in inferred
            },
            sent_in,
        )
        for key in keys.values():
            self._result_sent_in[key] = self._requests

    def _unplaced_id(
        self, key: str, used: set[str], cursors: dict[str, int]
    ) -> "_UnplacedId":
        """The id of a message no thread places, as the bridge has always given it.

        Every request message's id is recorded under its JSON (`_unplaced_key`),
        whether placement or this gave it, so a message keeps the id it had
        when its request was placed. A message takes the first id recorded for
        it that no earlier message of the request has, so the n-th equal
        message of a request takes the n-th id, and a new id if there is none.
        That may be an equal message's id recorded before its own, so a message
        placed under its own id and later not placed can take it.
        `cursors` holds, per key, how many of its ids the request has passed,
        so repeated messages don't each rescan them.
        """
        ids = self._message_ids.get(key, [])
        cursor = cursors.get(key, 0)
        while cursor < len(ids) and ids[cursor] in used:
            cursor += 1
        cursors[key] = cursor
        if cursor < len(ids):
            return _UnplacedId(ids[cursor], False)
        return _UnplacedId(uuid(), True)

    def _unlink(self, message_id: str) -> None:
        """Leave the calls of the handed reply with this id unlinked, for good.

        Once the bridge has lost or never had complete evidence of a reply's
        executions, an answer can't be matched to the execution it holds:
        when an unplaced message takes the reply's id (it may be an equal
        reply's copy, so a request that later places it under that id doesn't
        show which reply it is), the reply is handed out again
        (`_handed_calls`), or, in a sandbox bridge, one of its execution
        grants is evicted, an execution makes one of its proposals ambiguous,
        or another host call (an execution or a denied request) may repeat
        one of its calls while its answer is outstanding. A reply
        whose result tracking is dropped (`_await_result_message`) is
        recorded the same way.
        The id is kept for the rest of the sample (ids only, like the message
        pool), so executions completing later stay unlinked too.
        """
        root = self._edit_root(message_id)
        self._unlinked_replies.add(root)
        reply = self._awaited_results.get(root)
        if reply is not None:
            reply.events = dict.fromkeys(reply.events)

    def _edit_root(self, message_id: str) -> str:
        return self._edit_roots.get(message_id, message_id)

    def _version_id(self, message_id: str, message: ChatMessage, content: str) -> str:
        """`message_id`, or the id of an edited version if `message`'s content differs.

        Different content never shares an id. A placed message whose content
        is another form of the message it is placed as (a dialect's wire form
        of a reply) gets an id derived from the id it was placed by and its
        content, and an edited reply keeps the provider state recorded under
        that id.
        """
        if self._content_of(message_id, content) == content:
            return message_id
        edited_id = edit_id(message_id, content)
        self._content_of(edited_id, content)
        if isinstance(message, ChatMessageAssistant):
            copy_assistant_internal(message_id, edited_id)
        self._edit_roots[edited_id] = self._edit_root(message_id)
        return edited_id

    def _align_with_tracked(self, contents: list[str]) -> dict[int, str]:
        """Pair the request's leading messages with a thread it continues unchanged.

        A request that starts with the whole tracked thread, the latest
        generation's thread (input and output) or the latest request (a retry),
        each message sent as a form of the thread's message at its position
        (`_record_form`), may continue it: the scaffold can't invent assistant
        messages. Older threads don't count, since a request after drops can
        repeat one by chance. The longest such thread places the request's
        messages unless another conversation could hold the request's replies
        with a different reply in place of one of its own: one a kept thread
        holds (`_contested`), or one whose threads are no longer kept
        (`_dropped_holds`). That covers retries, rewinds and side calls whose
        replies repeat the thread's.
        """
        for thread in sorted(
            (self._tracked_ids, self._latest_generation, self._latest_request),
            key=len,
            reverse=True,
        ):
            if (
                self._contains(contents, thread)
                and not self._contested(contents, thread)
                and not self._dropped_holds(contents, thread)
            ):
                return {i: message_id for i, (message_id, _) in enumerate(thread)}
        return {}

    def _contested(
        self, contents: list[str], thread: Sequence[tuple[str, str]]
    ) -> bool:
        """Whether a kept thread could hold the request's replies placed by `thread` with another reply in place of one of its own.

        A request comes from a conversation holding its replies in order,
        whatever compaction dropped around them. If the tracked thread or a
        recent request or generation holds the replies `thread` would place in
        more than one way, or as different messages (edits aside), the request
        may continue that conversation instead.
        """
        replies = [
            (contents[i], message_id)
            for i, (message_id, role) in enumerate(thread)
            if role == "assistant"
        ]
        roots = [self._edit_root(message_id) for _, message_id in replies]
        for other in self._kept_threads():
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

    def _placement_state(self) -> "_PlacementState":
        """The threads `_align_with_tracked` reads, and what it reads of their ids, for the checkpoint.

        That includes what an id that is in no kept thread brings back when
        a request takes it again (`_unplaced_id`, so only an id recorded in
        `_message_ids`): its edit root and the forms other than its content. A reply's reach (`_held_replies`) is kept as
        recorded, since a thread that set it may no longer be kept.
        """
        threads: dict[int, tuple[int, list[tuple[str, str]]]] = {}

        def index(thread: list[tuple[str, str]]) -> int:
            return threads.setdefault(id(thread), (len(threads), thread))[0]

        recent = [index(thread) for thread in self._recent_threads]
        generation = index(self._latest_generation)
        request = index(self._latest_request)
        ids = {
            message_id
            for thread in (self._tracked_ids, *(t for _, t in threads.values()))
            for message_id, _ in thread
        }
        recorded = {message_id for _, message_id in self._recorded}
        return _PlacementState(
            threads=[thread for _, thread in threads.values()],
            recent_threads=recent,
            latest_generation=generation,
            latest_request=request,
            forms={
                id: sorted(forms)
                for id, forms in self._forms.items()
                if id in ids
                or (id in recorded and forms != {self._content_by_id.get(id)})
            },
            edit_roots=self._edit_roots,
            dropped_reach=self._dropped_reach,
            held_replies=self._held_replies,
            tracking=None
            if self._tracked_fps is None
            else _TrackingState(
                fps=list(self._tracked_fps),
                calls=self._tracked_calls,
                descends=self._tracked_descends,
                candidate_fps=None
                if self._candidate_fps is None
                else list(self._candidate_fps),
                last_message_count=self._last_message_count,
            ),
        )

    def _tracked_state(self) -> tuple[list[ChatMessage], ModelOutput]:
        """The tracked thread and output, as checkpointed.

        Before the first generation after a resume, these are the restored
        ones, which the checkpointed tracking state describes; `state` is
        still what the scaffold started from.
        """
        if self._resumed_state is not None:
            return self._resumed_state
        return self.state.messages, self.state.output

    def _restore_tracking(self, tracking: _TrackingState) -> None:
        """Pick the tracked thread as the checkpointed bridge would.

        Without it, the first generation after a resume is tracked whatever
        it is, so a side call there displaces the restored main thread, which
        `_align_with_tracked` places requests by.
        """
        self._tracked_fps = [_MessageFingerprint(*fp) for fp in tracking.fps]
        self._tracked_calls = tracking.calls
        self._tracked_descends = (
            None if tracking.descends is None else _Descent(tracking.descends)
        )
        self._candidate_fps = (
            None
            if tracking.candidate_fps is None
            else [_MessageFingerprint(*fp) for fp in tracking.candidate_fps]
        )
        self._last_message_count = tracking.last_message_count

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

    def _kept_threads(self) -> list[list[tuple[str, str]]]:
        """The threads whose replies placement keeps: the tracked thread, the latest generation's and request's, and the recent ones.

        The latest generation and request are kept whatever leaves the recent
        window, since `_align_with_tracked` places requests by them: requests
        entering the bridge while others are still generating (concurrent
        sub-agents) can push the latest generation out of the window, and its
        replies must not then count as dropped (`_dropped_holds`).
        """
        threads = (
            self._tracked_ids,
            self._latest_generation,
            self._latest_request,
            *self._recent_threads,
        )
        return list({id(thread): thread for thread in threads}.values())

    def _replace_kept(
        self, old: list[tuple[str, str]], new: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Keep `new` in place of `old` (the latest generation or request); returns `new`."""
        self._keep(new)
        self._drop(old)
        return new

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
            for content in self._forms.get(message_id, ()):
                self._dropped_reach[content] = max(
                    self._dropped_reach.get(content, 0), replies
                )

    def _dropped_holds(
        self, contents: list[str], thread: Sequence[tuple[str, str]]
    ) -> bool:
        """Whether a conversation whose threads are no longer kept may hold the replies `thread` would place.

        It may if one of its threads held a reply equal to one of them, which
        no kept thread holds, and at least as many replies.
        """
        replies = [i for i, (_, role) in enumerate(thread) if role == "assistant"]
        return any(
            self._dropped_reach.get(contents[i], 0) >= len(replies) for i in replies
        )

    def _embedding(
        self, replies: list[tuple[str, str]], ids: list[str]
    ) -> list[str] | None:
        """The edit roots of the earliest of `ids` holding `replies` in order, or `None` if they don't."""
        remaining = iter(ids)
        matched: list[str] = []
        for content, _ in replies:
            match = next((id for id in remaining if self._matches(content, id)), None)
            if match is None:
                return None
            matched.append(self._edit_root(match))
        return matched

    def _contains(self, contents: list[str], thread: Sequence[tuple[str, str]]) -> bool:
        return (
            bool(thread)
            and len(contents) >= len(thread)
            and all(
                self._matches(contents[i], message_id)
                for i, (message_id, _) in enumerate(thread)
            )
        )

    def _matches(self, content: str, message_id: str) -> bool:
        return content in self._forms.get(message_id, ())

    def _record_form(self, message_id: str, content: str) -> None:
        """Record that a message with `message_id` was sent or handed with `content`."""
        self._forms.setdefault(message_id, set()).add(content)
        self._content_of(message_id, content)

    def _content_of(self, message_id: str, content: str) -> str:
        """The content `message_id` has, recording `content` if it has none yet."""
        recorded = self._content_by_id.get(message_id)
        if recorded is None:
            self._content_by_id[message_id] = recorded = content
            self._ids_with_content[content] += 1
        return recorded

    def _record_forms(self, messages: list[ChatMessage]) -> None:
        for message in messages:
            if message.id is not None:
                self._record_form(message.id, content_hash(message))

    def _record_transported_reply(
        self, reply: ChatMessageAssistant, transported: list[ChatMessage]
    ) -> None:
        """Recognize `reply` by the form its dialect hands it back in.

        A dialect's wire form can drop parts of a reply (Responses and
        Anthropic an empty text, Google call ids), so a scaffold that sends the
        reply back unchanged sends that form.
        """
        if reply.id is None:
            return
        for message in transported:
            if isinstance(message, ChatMessageAssistant):
                self._forms.setdefault(reply.id, set()).add(content_hash(message))

    _message_ids: dict[str, list[str]]

    async def _track_state(
        self,
        input: list[ChatMessage],
        output: ModelOutput,
        transported: Sequence[list[ChatMessage]],
    ) -> None:
        """Track agent state by observing generations made through the bridge.

        `transported` holds each choice handed back to the scaffold in its
        dialect's wire form (see `_record_transported_reply`).

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
        if self._resumed_state is not None:
            # applied only now: the scaffold builds its prompt from the state
            # it starts with (see `__init__`)
            self.state.messages, self.state.output = self._resumed_state
            self._resumed_state = None
        for choice in output.choices:
            if choice.message.id is not None:
                self._record_form(choice.message.id, content_hash(choice.message))
        for choice, form in zip(output.choices, transported):
            self._record_transported_reply(choice.message, form)

        # every choice's thread, since the scaffold may continue any of them;
        # the primary's last, so it stays kept when the window is full
        threads: list[list[tuple[str, str]]] = [
            [(m.id, m.role) for m in [*input, choice.message] if m.id is not None]
            for choice in output.choices
        ]
        for thread in [*threads[1:], threads[0]]:
            self._remember_thread(thread)
        self._latest_generation = self._replace_kept(
            self._latest_generation, threads[0]
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


def _call_key(call: ToolCall) -> tuple[str, str]:
    return call.function, canonical_tool_arguments(call.arguments)


def _named_result_key(message: ChatMessageTool, call: ToolCall | None) -> str:
    """`content_hash` of a result that names its function rather than its call.

    The result is keyed by the function and arguments of `call`, the call it
    answers, or by its function alone when the request has no such call.
    """
    answered = json.dumps(_call_key(call)) if call else f"function:{message.function}"
    return content_hash(message.model_copy(update={"tool_call_id": answered}))


def _unplaced_key(message: ChatMessage) -> str:
    """The key a request message's id is recorded under: its JSON without its id.

    `json.dumps` escapes a lone surrogate, so no two messages share a key.
    """
    message_json: dict[str, Any] = jsonable_python(message)
    message_json.pop("id", None)
    return message_json_hash(json.dumps(message_json))


class _UnplacedId(NamedTuple):
    id: str

    new: bool
    """Whether no message was given the id before."""


class _MessageFingerprint(NamedTuple):
    """(role, hash-of-text) identity used for thread prefix comparisons.

    Deliberately excludes message ids and metadata: messages round-trip through
    the scaffold's own conversation store between calls, so only role and text
    content are stable across the main loop's successive requests.
    """

    role: str
    text_hash: str


def _message_fingerprint(message: ChatMessage) -> _MessageFingerprint:
    return _MessageFingerprint(
        role=message.role, text_hash=mm3_hash(shown_text(message.content))
    )


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
    text = shown_text(message.content)
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        interior = stripped[1:-1].strip()
        if interior == f"{ATTACHMENT_PROTOCOL}{initial.text_hash}" or (
            initial_text and interior == initial_text
        ):
            return _Descent.QUOTED
    if (
        len(initial_text) >= _ANCHOR_CONTAINMENT_MIN_CHARS and initial_text in text
    ) or f"{ATTACHMENT_PROTOCOL}{initial.text_hash}" in text:
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
