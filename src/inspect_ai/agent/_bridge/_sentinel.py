import hashlib
import json
from collections import OrderedDict
from contextlib import AbstractContextManager, ExitStack, nullcontext
from copy import deepcopy
from dataclasses import dataclass
from functools import cached_property, partial
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Literal,
    NamedTuple,
    Sequence,
    TypeVar,
)

import anyio
from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._sentinel._agent_state import bridge_request
from inspect_ai._sentinel._context import SentinelFailure, checks_tool_calls
from inspect_ai._util._async import tg_collect
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._call_tools import decisive_sentinel_exception, repeated_call_ids
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._providers._google_computer_use_name import (
    gemini_computer_action_names,
)
from inspect_ai.tool._tool import Tool, ToolResult
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallError,
    ToolCallViewer,
    ToolCallViewError,
)
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._span import in_agent_span

if TYPE_CHECKING:
    from inspect_sentinel import Decision

    from inspect_ai.event._model import ModelEvent

logger = getLogger(__name__)

T = TypeVar("T")

_MAX_PROPOSALS = 1000

# a result no assistant message in the request accounts for, or a host call no
# proposal does, has no message that made the call
_NO_MESSAGE_ID = ""


class Produced(NamedTuple):
    """The generation that produced a bridged call, and the agent span it ran in."""

    event: "ModelEvent"
    """What the model was sent (`input`, `tools`, `tool_choice`)."""

    agent_span_id: str | None
    """The agent span current during the generation: the call's conversation."""

    def scope(self) -> AbstractContextManager[None]:
        return in_agent_span(self.agent_span_id)


class SentinelCheck(NamedTuple):
    handed: ToolCall
    """The call as handed to the scaffold (the model's id, the approved arguments)."""

    call: ToolCall
    """The call the steps show (the model's id; a dispatched call's target)."""

    viewer: ToolCallViewer | None
    message: str

    message_id: str | None
    """The id of the assistant message that made the call."""

    producer: Produced | None = None
    """The generation that produced the call, if the bridge knows it; the steps
    take what the model was sent from it, and its conversation, and without it
    have no input and the bridge's current conversation."""

    execution_id: str | None = None
    """The handout of the call this check is for (`_Handouts.hand_over`),
    or None for a host call no proposal accounts for."""

    alternatives: tuple["SentinelCheck", ...] = ()
    """Checks for other host tools denoted by the same handed call."""


class BridgedRequest(NamedTuple):
    """A scaffold request, as the bridge tells calls apart by it."""

    key: str
    """Its conversation's digest (`bridged_request`): a retry of the request
    has the same."""

    ids: frozenset[str]
    """The call ids in its conversation (`history_ids`)."""


def bridged_request(input: Sequence[ChatMessage]) -> BridgedRequest:
    # message ids are the bridge's, assigned from the messages' content; the
    # agent controls its messages, so the digest must be collision-resistant
    return BridgedRequest(
        _digest(
            [
                to_json_str_safe(message.model_copy(update={"id": None}))
                for message in input
            ]
        ),
        history_ids(input),
    )


class _Handed(NamedTuple):
    """What the bridge keeps for each call id it has handed to the scaffold."""

    function: str

    proposed: str | None
    """The call as the model proposed it (`_call_key`), or None when several
    calls of its response shared the id."""

    handed: str
    """The call as handed over, with the arguments approval gave it (`_call_key`)."""

    execution_id: str | None
    """The call's latest handout, or None for a call only in a rejected turn."""

    request: str
    """The request it was handed over or rejected in (`BridgedRequest.key`)."""


class _SavedHandouts(BaseModel):
    reserved_ids: list[str]
    handed: dict[str, _Handed]
    checked: list[str]


class _Result(NamedTuple):
    keys: list[str]
    """The result's identity (first) and any it also answers for."""

    checks: tuple[SentinelCheck, ...]
    """The possible targets to check; a host execution has only its actual target."""

    message: ChatMessageTool


class _Claim(NamedTuple):
    result: _Result

    event: anyio.Event
    """Set on release; the `running` entry of each of the result's keys this
    claim took (a key another claim already held stays that claim's)."""


class _Claimed(NamedTuple):
    owned: list[_Claim]
    waiting: list[anyio.Event]


@dataclass
class _Call:
    call: ToolCall
    text: str
    position: int

    @cached_property
    def key(self) -> str:
        return _call_key(self.call)


class _Handouts:
    """The calls a bridge has handed to the scaffold, and the checks of their results.

    A call is handed over under the model's id. Each handout is an execution
    with its own `execution_id`: a scaffold retry served from the model cache
    hands the same call over again, under the same id, and its result is that
    of the latest handout, the one the scaffold received.

    A call gets a fresh id instead (`reused`) when the model's id can't name
    it: an empty id, or one that already names another call (Claude Code
    drops a repeated id and the result under it). The ids handed over or
    rejected, with their calls, and the ids seen in requests
    (`reserved_ids`) are kept for the life of the bridge and in its
    checkpoint (`saved`), apart from the proposals (bounded).

    Each execution's result is checked once: a result is identified by its
    call's id, the call as proposed and the result's exact content
    (`_content_key`), so replays are not checked again, while different
    content for the same execution, down to its whitespace, is. A result gets
    its proposal's context; once the proposal is evicted, the request's
    conversation and no model input.

    A result under an id the bridge never handed out, or one several calls of
    a response shared (a scaffold that rewrites ids, or one answering no call),
    can't be matched to an execution. It is checked once per conservative key,
    its call's function and arguments and its content (`_call_key`), with the
    request's conversation and no model input, never another call's context;
    an identical result of another execution is not checked again. Every
    checked result also records that key, so a matched result reported again
    under another id is not checked twice.

    A host call's result is checked when the call executes, and that result,
    as delivered, is recorded as checked for its call; other content the
    scaffold reports for the call is checked like a scaffold-run call's.

    The results in the state the bridge starts with were in the agent's
    conversation before the bridge ran, and are not checked again, as a native
    agent handed a conversation does not check its results again
    (`inherited_result_keys`). Each is recorded under its conservative key,
    taken when the bridge is first constructed and kept in its checkpoint, so
    a result reported with other content (including one changed in place
    since, before or after a resume) is checked. Their call ids are reserved
    at the same point (`history_ids`).

    Held by its bridge, since a failure's traceback references the bridge.
    """

    def __init__(self, saved: _SavedHandouts) -> None:
        self.handed: dict[str, _Handed] = dict(saved.handed)
        self.reserved_ids: set[str] = set(saved.reserved_ids)
        self.proposals: OrderedDict[str, SentinelCheck] = OrderedDict()
        self.checked: set[str] = set(saved.checked)
        self.running: dict[str, anyio.Event] = {}
        self.failed: dict[str, Exception] = {}

    def saved(self) -> _SavedHandouts:
        """What a resumed bridge needs to hand over calls and match results as this one does.

        Proposals hold their generation and viewer, so a resumed bridge
        matches a result as it would after the proposal's eviction. A check
        that was running or failed is made again.
        """
        return _SavedHandouts(
            reserved_ids=sorted(self.reserved_ids),
            handed=dict(self.handed),
            checked=sorted(self.checked),
        )

    def reserve(self, ids: Iterable[str]) -> None:
        self.reserved_ids.update(ids)

    def function(self, call_id: str) -> str | None:
        """The function of the call handed over under `call_id`, if any."""
        handed = self.handed.get(call_id)
        return handed.function if handed is not None else None

    def reused(
        self,
        call_id: str,
        calls: Sequence[ToolCall],
        request: BridgedRequest,
        siblings: AbstractSet[str] = frozenset(),
    ) -> bool:
        """Whether the model's id for `calls` (those of a response under it) names another call.

        An id the bridge proposed before (handed over or rejected) names
        another call when it was another function or arguments as proposed, or
        several calls. The same call proposed again keeps its id: a retry of
        its request (served from the model cache, or after a rejection), or
        the call again in a later turn or another conversation, whose results
        then get no proposal's context (`hand_over`). Any other id names
        another call when it is empty, in the request's conversation or
        reserved: the bridge can't tell which call it was. So
        does an id a Gemini CLI echo (`name__id`, `_echoes`) can't tell apart
        from a reserved or handed one, or one of the response's other calls
        (`siblings`).
        """
        if not call_id:
            return True
        if any(
            echo in self.reserved_ids or echo in self.handed or echo in siblings
            for call in calls
            for echo in _echoes(call)
        ):
            return True
        handed = self.handed.get(call_id)
        if handed is None:
            return call_id in request.ids or call_id in self.reserved_ids
        return (
            handed.proposed is None
            or len(calls) > 1
            or _call_key(calls[0]) != handed.proposed
        )

    def hand_over(
        self,
        request: BridgedRequest,
        proposed: Sequence[ToolCall],
        handed: Sequence[ToolCall],
        checks: Sequence[SentinelCheck] | None,
    ) -> list[SentinelCheck] | None:
        """Record a response's calls as handed over in `request`, each a new execution.

        `proposed` are the calls as the model proposed them, `handed` as
        approval gave them, and `checks` their `tool_result` checks, in order
        (None without a sentinel). Returns the checks with their execution ids.
        """
        shared = repeated_call_ids(handed)
        issued: list[SentinelCheck] = []
        for index, (model_call, call) in enumerate(zip(proposed, handed, strict=True)):
            # handed over before for another request, not a retry of it: which
            # handout a result answers can't be told, so neither keeps a proposal
            earlier = self.handed.get(call.id)
            ambiguous = (
                earlier is not None
                and earlier.execution_id is not None
                and earlier.request != request.key
            )
            execution_id = uuid()
            self.handed[call.id] = _Handed(
                call.function,
                None if call.id in shared else _call_key(model_call),
                _call_key(call),
                execution_id,
                request.key,
            )
            if checks is None:
                continue
            check = checks[index]
            check = check._replace(
                execution_id=execution_id,
                alternatives=tuple(
                    alternative._replace(execution_id=execution_id)
                    for alternative in check.alternatives
                ),
            )
            issued.append(check)
            self.proposals.pop(call.id, None)
            if call.id in shared or ambiguous:
                continue
            self.proposals[call.id] = check
            while len(self.proposals) > _MAX_PROPOSALS:
                self.proposals.popitem(last=False)
                warn_once(
                    logger,
                    f"More than {_MAX_PROPOSALS} bridged tool calls have been "
                    "handed to the scaffold; the oldest proposal was dropped, so "
                    "the sentinel's tool_result check of a call handed over more "
                    f"than {_MAX_PROPOSALS} calls ago sees only the conversation "
                    "that carries its result, and no model input.",
                )
        return issued if checks is not None else None

    def propose(self, request: BridgedRequest, calls: Sequence[ToolCall]) -> None:
        """Record a response's calls under the ids they keep, before approval and the sentinel review them.

        So a concurrent request's call under one of the ids is another call's
        (`reused`), whether these are then handed over (`hand_over`) or
        rejected, when the model sees them but the scaffold never runs them.
        """
        shared = repeated_call_ids(calls)
        for call in calls:
            if call.id not in self.handed:
                key = _call_key(call)
                self.handed[call.id] = _Handed(
                    call.function,
                    None if call.id in shared else key,
                    key,
                    None,
                    request.key,
                )

    def latest(self, check: SentinelCheck) -> SentinelCheck:
        """The check for the latest handout of `check`'s call and target."""
        proposal = self.proposals.get(check.handed.id)
        if proposal is None or check.execution_id is None:
            return check
        return next(
            (
                target
                for target in (proposal, *proposal.alternatives)
                if target.call.function == check.call.function
            ),
            check,
        )

    def result_keys(self, call: ToolCall, content_key: str) -> list[str]:
        """The keys a result of the handed `call` with `content_key` is checked under."""
        keys = [_digest(["call", _call_key(call), content_key])]
        handed = self.handed.get(call.id)
        if handed is not None and handed.proposed is not None:
            keys.insert(0, _digest(["handed", call.id, handed.proposed, content_key]))
        return keys

    def claim(self, input: list[ChatMessage]) -> _Claimed:
        claimed = _Claimed([], [])
        keys: set[str] = set()
        for message, found in _answers(input):
            result = self._result(input, message, found)
            key = result.keys[0]
            if key in keys or key in self.checked:
                continue
            if key in self.failed:
                raise self.failed[key]
            if key in self.running:
                claimed.waiting.append(self.running[key])
                continue
            # a result whose identity another of the request's results also
            # answers for is checked by that result
            keys.update(result.keys)
            claimed.owned.append(_Claim(result, anyio.Event()))
        for claim in claimed.owned:
            self._take(claim)
        return claimed

    def _take(self, claim: _Claim) -> None:
        for key in claim.result.keys:
            self.running.setdefault(key, claim.event)

    def _result(
        self,
        input: list[ChatMessage],
        message: ChatMessageTool,
        found: _Call | None,
    ) -> _Result:
        call_id = message.tool_call_id or ""
        handed = self.handed.get(call_id)
        if handed is not None and handed.proposed is not None:
            content = _content_key(message)
            keys = [
                _digest(["handed", call_id, handed.proposed, content]),
                _digest(["call", handed.handed, content]),
            ]
            proposal = self.proposals.get(call_id)
            if proposal is not None:
                return _Result(keys, (proposal, *proposal.alternatives), message)
            call = (
                found.call
                if found is not None
                else ToolCall(id=call_id, function=handed.function, arguments={})
            )
        else:
            call, key = _unissued(message, found)
            keys = [key]
        check = SentinelCheck(
            call,
            call,
            None,
            found.text if found is not None else "",
            input[found.position].id if found is not None else _NO_MESSAGE_ID,
        )
        return _Result(keys, (check,), message)

    async def check(
        self,
        bridge: AgentBridge,
        result: _Result,
        output: ToolResult,
        truncated: tuple[int, int] | Literal[False] | None = None,
    ) -> None:
        try:
            for check in result.checks:
                await _tool_result(
                    bridge,
                    check,
                    result.message,
                    output,
                    truncated,
                    reject_on_viewer_error=len(result.checks) > 1,
                )
        except Exception as ex:
            for key in result.keys:
                self.failed.setdefault(key, ex)
            raise
        self.checked.update(result.keys)

    async def check_running(
        self,
        bridge: AgentBridge,
        result: _Result,
        output: ToolResult,
        truncated: tuple[int, int] | Literal[False] | None,
    ) -> None:
        """Check a result claimed outside a request (a host call's), as running."""
        claim = _Claim(result, anyio.Event())
        self._take(claim)
        try:
            await self.check(bridge, result, output, truncated)
        finally:
            self.release(claim)

    def release(self, claim: _Claim) -> None:
        # a check that did not finish is claimed again by the next request
        # carrying its result
        for key in claim.result.keys:
            if self.running.get(key) is claim.event:
                del self.running[key]
        claim.event.set()


def _echoes(call: ToolCall) -> set[str]:
    """The other ids a Gemini CLI echo of `call`'s id can be read back as.

    Gemini CLI may send an id back prefixed with its call's wire name
    (`name__id`), which the Google dialect strips for a call handed over to
    that function (`_function_part_id`): the prefixed id, and the id with such
    a prefix stripped.
    """
    names = wire_names(call.function, call.arguments)
    echoes = {f"{name}__{call.id}" for name in names}
    echoes |= {
        call.id.removeprefix(f"{name}__")
        for name in names
        if call.id.startswith(f"{name}__")
    }
    return echoes - {call.id, ""}


def wire_names(function: str, arguments: dict[str, Any]) -> set[str]:
    """The names a Gemini scaffold can send a call to `function` under."""
    names = {function.strip() or "generic_tool"}
    if function == "computer":
        names |= gemini_computer_action_names(arguments)
    return names


def _answers(
    input: Sequence[ChatMessage],
) -> Iterator[tuple[ChatMessageTool, _Call | None]]:
    """Each result in a request, with the call it answers in the request, if any."""
    calls: dict[str, _Call] = {}
    unanswered: dict[str, list[_Call]] = {}
    for index, message in enumerate(input):
        if isinstance(message, ChatMessageAssistant):
            unanswered = {}
            # a message with several text parts joins them on each read
            text = message.text if message.tool_calls else ""
            for call in message.tool_calls or []:
                calls[call.id] = _Call(call, text, index)
                unanswered.setdefault(call.id, []).append(calls[call.id])
        elif isinstance(message, ChatMessageTool):
            result_id = message.tool_call_id or ""
            found = (
                unanswered[result_id].pop(0)
                if unanswered.get(result_id)
                else calls.get(result_id)
            )
            yield message, found


def _unissued(message: ChatMessageTool, found: _Call | None) -> tuple[ToolCall, str]:
    """A result under an id the bridge never handed out: the call it answers, and its conservative key."""
    call = (
        found.call
        if found is not None
        else ToolCall(
            id=message.tool_call_id or "",
            function=message.function or "",
            arguments={},
        )
    )
    call_key = (
        found.key if found is not None else _call_key(call, message.function or "")
    )
    return call, _digest(["call", call_key, _content_key(message)])


def _call_key(call: ToolCall, orphan: str | None = None) -> str:
    """A call's conservative identity: its function and arguments.

    For a result answering no call in its request, `orphan` is the function the
    result names, and the arguments are unknown.
    """
    identity: Any = (
        ["orphan", orphan]
        if orphan is not None
        else [call.function, _json_canonical(call.arguments)]
    )
    return _digest(identity)


def _json_canonical(value: Any) -> Any:
    # as `_json_equal`: 5 and 5.0 are the same argument, True and 1 are not
    value = to_jsonable_python(value, fallback=str)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _json_canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_canonical(item) for item in value]
    return value


def _content_key(result: ChatMessageTool) -> str:
    """A result as the model receives it: its function, its content, in order and exactly, and its error.

    Whitespace and the order of text and other parts are meaningful (in code,
    paths and instructions), so any difference is a different result, checked
    again; so is the function it is reported under, which a provider can send
    the model (Google's `FunctionResponse.name`); so is a text part's
    `internal`, which a provider can send in its text (Anthropic), serialized
    as it is sent there (`content_internal_tag()`), in its key order. Other
    parts' `internal` never reaches a model and is left out; a string and a
    single text part are the same content.
    """
    content = (
        [ContentText(text=result.content)]
        if isinstance(result.content, str)
        else result.content
    )
    parts: list[dict[str, Any]] = []
    for part in content:
        parts.append(part.model_dump(exclude={"internal"}, exclude_none=True))
        if isinstance(part, ContentText) and part.internal is not None:
            parts[-1]["internal"] = json.dumps(part.internal)
    error = (
        [result.error.type, result.error.message] if result.error is not None else None
    )
    # a provider sends no function as an empty name
    return _digest(
        to_jsonable_python([result.function or "", parts, error], fallback=str)
    )


def _digest(value: Any) -> str:
    # the agent controls its results, so a key standing for a checked result
    # must be collision-resistant
    encoded = json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def inherited_result_keys(input: Sequence[ChatMessage]) -> frozenset[str]:
    """The keys of the results a bridge starts with, which it does not check.

    Taken when the bridge is first constructed, from the messages as they are
    then, and restored from its checkpoint on resume: a result later changed
    in place has a different key and is checked.
    """
    return frozenset(_unissued(message, found)[1] for message, found in _answers(input))


def history_ids(input: Sequence[ChatMessage]) -> frozenset[str]:
    """The call ids in a conversation: its calls' and its results'."""
    ids: set[str] = set()
    for message in input:
        if isinstance(message, ChatMessageAssistant):
            ids.update(call.id for call in message.tool_calls or [] if call.id)
        elif isinstance(message, ChatMessageTool) and message.tool_call_id:
            ids.add(message.tool_call_id)
    return frozenset(ids)


def checks_bridged_results() -> bool:
    """Whether the sentinel checks the result of a bridged call made here."""
    if not checks_tool_calls():
        return False
    from inspect_ai._sentinel._dispatch import watches_tool_results

    return watches_tool_results()


async def sentinel_tool_call(
    bridge: AgentBridge,
    message: str,
    message_id: str | None,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    producer: Produced | None,
) -> "Decision | None":
    from inspect_ai._sentinel._dispatch import sentinel_before_tool_call

    with producer.scope() if producer is not None else nullcontext():
        return await _guarded(
            bridge,
            partial(
                sentinel_before_tool_call,
                message,
                message_id,
                call,
                viewer,
                history=None,
                producer=producer.event if producer is not None else None,
                bridge=True,
            ),
        )


def sentinel_unproposed_host_check(
    bridge: AgentBridge, tool: str, arguments: dict[str, Any], tool_fn: Tool
) -> SentinelCheck | None:
    # a host call no proposal accounts for is checked with the conversation the
    # bridge last saw, as a scaffold-reported result without a proposal is
    if not checks_tool_calls():
        return None
    call = ToolCall(id=f"call_{tool}_{uuid()[:8]}", function=tool, arguments=arguments)
    return SentinelCheck(
        call,
        call,
        ToolDef(tool_fn).viewer,
        "",
        _NO_MESSAGE_ID,
    )


async def sentinel_host_tool_result(
    bridge: AgentBridge,
    check: SentinelCheck,
    content: str | list[Content],
    output: ToolResult,
    error: ToolCallError | None = None,
    truncated: tuple[int, int] | Literal[False] = False,
    candidates: Sequence[SentinelCheck] = (),
) -> None:
    """Check a host call's result as delivered, recording it for its executions.

    The result is recorded as checked for the call, or, for a call that
    matched proposals of several calls (`candidates`, when the service can't
    tell which execution it is), for each of them, so the scaffold reporting it
    is not checked again. A host call no proposal accounts for was handed over
    as no call, so no result the scaffold reports can match it.

    The call is the bridged scaffold's, so the check does not see the enclosing
    agent's messages, as the stages of a bridge request don't
    (`bridge_request()`).
    """
    result = ChatMessageTool(
        content=content,
        tool_call_id=check.handed.id,
        function=check.call.function,
        error=error,
    )
    executions = candidates or ([check] if check.execution_id is not None else [])
    keys: list[str] = []
    content_keys: dict[str, str] = {}
    for execution in executions:
        # as the scaffold reports it: under the function it was handed
        function = execution.handed.function
        if function not in content_keys:
            content_keys[function] = _content_key(
                result.model_copy(update={"function": function})
            )
        keys += bridge._handouts.result_keys(execution.handed, content_keys[function])
    keys = keys or [f"unproposed:{uuid()}"]
    with bridge_request():
        await bridge._handouts.check_running(
            bridge, _Result(keys, (check,), result), output, truncated
        )


async def sentinel_tool_results(bridge: AgentBridge, input: list[ChatMessage]) -> None:
    if not checks_tool_calls():
        return
    result_checks = bridge._handouts
    while True:
        claimed = result_checks.claim(input)
        if claimed.owned:
            with ExitStack() as releases:
                for claim in claimed.owned:
                    releases.callback(result_checks.release, claim)
                await tg_collect(
                    [
                        partial(
                            result_checks.check,
                            bridge,
                            claim.result,
                            _output(claim.result.message),
                        )
                        for claim in claimed.owned
                    ]
                )
        if not claimed.waiting:
            return
        for running in claimed.waiting:
            await running.wait()


def _output(result: ChatMessageTool) -> ToolResult:
    # the scaffold's rendering of the result: its untruncated output never
    # reaches the bridge
    if isinstance(result.content, str):
        return result.content
    return [
        content
        for content in result.content
        if isinstance(
            content,
            ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument,
        )
    ]


async def _tool_result(
    bridge: AgentBridge,
    check: SentinelCheck,
    result: ChatMessageTool,
    output: ToolResult,
    truncated: tuple[int, int] | Literal[False] | None,
    reject_on_viewer_error: bool = False,
) -> None:
    from inspect_ai._sentinel._dispatch import sentinel_after_tool_call

    producer = check.producer
    with producer.scope() if producer is not None else nullcontext():
        try:
            await _guarded(
                bridge,
                partial(
                    sentinel_after_tool_call,
                    check.message,
                    check.message_id,
                    # a copy, so a monitor can't change the call the check keeps
                    deepcopy(check.call),
                    result,
                    output,
                    truncated,
                    check.viewer,
                    history=None,
                    producer=producer.event if producer is not None else None,
                    reject_on_viewer_error=reject_on_viewer_error,
                    bridge=True,
                ),
            )
        except ToolCallViewError as ex:
            bridge.request_fail(ex)
            raise


async def _guarded(bridge: AgentBridge, run: Callable[[], Awaitable[T]]) -> T:
    # outcomes that end the sample go through the bridge, since a sandbox
    # bridge's service task can't raise them to the sample runner
    limit: LimitExceededError | None = None
    try:
        return await run()
    except TerminateSampleError as ex:
        bridge.request_terminate(str(ex))
    except SentinelFailure as ex:
        inner = decisive_sentinel_exception(ex.error)
        if not isinstance(inner, LimitExceededError):
            if isinstance(inner, TerminateSampleError):
                bridge.request_terminate(str(inner))
            bridge.request_fail(ex)
            raise
        limit = inner
    # raised outside the handler: the failure's cause is the limit, so linking
    # the limit back to it (as a cause or context) would make a cycle
    if limit is not None:
        raise limit
