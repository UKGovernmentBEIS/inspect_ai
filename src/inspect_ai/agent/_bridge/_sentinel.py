import json
from collections import OrderedDict
from dataclasses import replace
from functools import partial
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    NamedTuple,
    Sequence,
    TypeVar,
)

import anyio
from pydantic_core import to_jsonable_python
from shortuuid import uuid

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
from inspect_ai._util.hash import mm3_hash
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool, ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallError, ToolCallViewer
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError

if TYPE_CHECKING:
    from inspect_sentinel import Decision

    from inspect_ai.event._model import ModelEvent

logger = getLogger(__name__)

T = TypeVar("T")

_MAX_PROPOSALS = 1000

# a result no assistant message in the request accounts for, or a host call no
# proposal does, has no message that made the call
_NO_MESSAGE_ID = ""


class SentinelCheck(NamedTuple):
    handed: ToolCall
    """The call as handed to the scaffold (the model's id, the approved arguments)."""

    call: ToolCall
    """The call the steps show (the model's id; a dispatched call's target)."""

    viewer: ToolCallViewer | None
    message: str

    message_id: str | None
    """The id of the assistant message that made the call."""

    history: list[ChatMessage]

    producer: "ModelEvent | None" = None
    """The generation that proposed the call (`sentinel_producer`)."""

    producer_resolved: bool = False
    """Whether `producer` is resolved, even to None; if not, the steps look for
    the call's generation in the transcript."""

    token: str | None = None
    """The id the scaffold was handed for the call (`sentinel_tokens`), or None
    for a host call no proposal accounts for."""


class _Identity(NamedTuple):
    """What the bridge keeps for every token it has handed out, for good."""

    call_id: str
    """The model's id for the call."""

    function: str

    call_key: str
    """The call's conservative identity (`_call_key`)."""


class _Result(NamedTuple):
    keys: list[str]
    """The result's identity (first) and any it also answers for."""

    check: SentinelCheck
    message: ChatMessageTool


class _Claimed(NamedTuple):
    owned: list[_Result]
    waiting: list[anyio.Event]


class _Call(NamedTuple):
    call: ToolCall
    text: str
    position: int


class _ResultChecks:
    """The `tool_result` checks for the results the scaffold reports.

    Each call handed to the scaffold gets a token, unique for the bridge, as
    its id (`sentinel_tokens`): the model's own id when the bridge has not
    handed that id out before, and a new one otherwise. A result reported
    under a token is the result of that execution, however the scaffold has
    rewritten, compacted or reformatted the rest of its conversation. Tokens
    are kept for the life of the bridge, apart from the proposals (bounded), so
    an evicted proposal can never make an older execution match a newer one.

    Each execution's result is checked once: a result is identified by its
    token and its content (`_content_key`, which ignores whitespace and how
    text is split into parts), so replays are not checked again, while
    different content for the same execution is. A result under a token gets
    its proposal's context; once the proposal is evicted, the request's
    conversation and no model input.

    A result whose id the bridge never handed out (a scaffold that drops or
    rewrites ids, or one answering no call) can't be matched to an execution.
    It is checked once per conservative key, its call's function and arguments
    and its content (`_call_key`), with the request's conversation and no
    model input, never another call's context; an identical result of another
    execution is not checked again. Every checked result also records that
    key, so a matched result reported again without its token is not checked
    twice.

    A host call's result is checked when the call executes, and that result,
    as delivered, is recorded as checked under the call's token; other content
    the scaffold reports for the call is checked like a scaffold-run call's.

    Held by its bridge, since a failure's traceback references the bridge.
    """

    def __init__(self) -> None:
        self.identities: dict[str, _Identity] = {}
        self.proposals: OrderedDict[str, SentinelCheck] = OrderedDict()
        self.checked: set[str] = set()
        self.running: dict[str, anyio.Event] = {}
        self.failed: dict[str, Exception] = {}

    def issue(self, checks: Sequence[SentinelCheck]) -> list[SentinelCheck]:
        issued: list[SentinelCheck] = []
        for check in checks:
            token = check.handed.id
            while not token or token in self.identities:
                token = f"call_{uuid()}"
            self.identities[token] = _Identity(
                check.call.id, check.handed.function, _call_key(check.handed)
            )
            issued.append(check._replace(token=token))
            self.proposals[token] = issued[-1]
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
        return issued

    def claim(self, input: list[ChatMessage]) -> _Claimed:
        claimed = _Claimed([], [])
        keys: set[str] = set()
        calls: dict[str, _Call] = {}
        unanswered: dict[str, list[_Call]] = {}
        for index, message in enumerate(input):
            if isinstance(message, ChatMessageAssistant):
                unanswered = {}
                for call in message.tool_calls or []:
                    calls[call.id] = _Call(call, message.text, index)
                    unanswered.setdefault(call.id, []).append(calls[call.id])
            elif isinstance(message, ChatMessageTool):
                result_id = message.tool_call_id or ""
                found = (
                    unanswered[result_id].pop(0)
                    if unanswered.get(result_id)
                    else calls.get(result_id)
                )
                result = self._result(input, index, message, found)
                key = result.keys[0]
                if key in keys or key in self.checked:
                    continue
                if key in self.failed:
                    raise self.failed[key]
                if key in self.running:
                    claimed.waiting.append(self.running[key])
                    continue
                keys.add(key)
                claimed.owned.append(result)
        for result in claimed.owned:
            event = anyio.Event()
            for key in result.keys:
                self.running.setdefault(key, event)
        return claimed

    def _result(
        self,
        input: list[ChatMessage],
        index: int,
        message: ChatMessageTool,
        found: _Call | None,
    ) -> _Result:
        identity = self.identities.get(message.tool_call_id or "")
        content = _content_key(message)
        if identity is not None:
            token = message.tool_call_id or ""
            keys = [
                mm3_hash(f"token:{token}:{content}"),
                mm3_hash(f"call:{identity.call_key}:{content}"),
            ]
            proposal = self.proposals.get(token)
            if proposal is not None:
                return _Result(keys, proposal, message)
            call = (
                replace(found.call, id=identity.call_id)
                if found is not None
                else ToolCall(
                    id=identity.call_id, function=identity.function, arguments={}
                )
            )
        else:
            call = (
                found.call
                if found is not None
                else ToolCall(
                    id=message.tool_call_id or "",
                    function=message.function or "",
                    arguments={},
                )
            )
            orphan = None if found is not None else message.function or ""
            keys = [mm3_hash(f"call:{_call_key(call, orphan)}:{content}")]
        # the history ends with the call's assistant message, as on the native
        # path; a result answering no call in the request has none
        history = input[: found.position + 1 if found is not None else index]
        check = SentinelCheck(
            call,
            call,
            None,
            found.text if found is not None else "",
            input[found.position].id if found is not None else _NO_MESSAGE_ID,
            history,
        )
        return _Result(keys, check, message)

    async def check(
        self,
        bridge: AgentBridge,
        result: _Result,
        output: ToolResult,
        truncated: tuple[int, int] | Literal[False] | None = None,
    ) -> None:
        try:
            await _tool_result(bridge, result.check, result.message, output, truncated)
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
        event = anyio.Event()
        for key in result.keys:
            self.running.setdefault(key, event)
        try:
            await self.check(bridge, result, output, truncated)
        finally:
            for key in result.keys:
                if self.running.get(key) is event:
                    del self.running[key]
            event.set()

    def release(self, result: _Result) -> None:
        # a check that did not finish is claimed again by the next request
        # carrying its result
        event = self.running.get(result.keys[0])
        for key in result.keys:
            if self.running.get(key) is event:
                del self.running[key]
        if event is not None:
            event.set()


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
    return mm3_hash(json.dumps(identity, sort_keys=True))


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
    """A result's content, as the same whatever its whitespace or text parts.

    Text is compared without whitespace, so re-wrapping, trimming or splitting
    it into parts differently is not a different result. Other content
    compares as itself, less fields that never reach a model (`internal`).
    """
    content = (
        [ContentText(text=result.content)]
        if isinstance(result.content, str)
        else result.content
    )
    text = "".join(
        "".join(part.text.split()) for part in content if isinstance(part, ContentText)
    )
    others = [
        part.model_dump(exclude={"internal"}, exclude_none=True)
        for part in content
        if not isinstance(part, ContentText)
    ]
    error = (
        [result.error.type, "".join(result.error.message.split())]
        if result.error is not None
        else None
    )
    return mm3_hash(
        json.dumps(
            to_jsonable_python([text, others, error], fallback=str), sort_keys=True
        )
    )


def _result_checks(bridge: AgentBridge) -> _ResultChecks:
    if bridge._sentinel_results is None:
        bridge._sentinel_results = _ResultChecks()
    return bridge._sentinel_results


async def sentinel_tool_call(
    bridge: AgentBridge,
    message: str,
    message_id: str | None,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
    producer: "ModelEvent | None",
) -> "Decision | None":
    from inspect_ai._sentinel._dispatch import sentinel_before_tool_call

    return await _guarded(
        bridge,
        partial(
            sentinel_before_tool_call,
            message,
            message_id,
            call,
            viewer,
            history,
            producer,
            find_producer=False,
        ),
    )


async def sentinel_generation(
    bridge: AgentBridge, message_id: str | None
) -> "ModelEvent | None":
    """The transcript's latest generation of `message_id`, when tool calls are checked."""
    if not checks_tool_calls():
        return None
    return await _produced_event(bridge, message_id)


async def sentinel_producer(
    bridge: AgentBridge,
    message_id: str | None,
    captured: "ModelEvent | None",
    filtered: bool,
) -> "ModelEvent | None":
    """The generation whose output is the response under review, for both tool stages.

    `captured` is the bridge's generation, taken before any response filter
    ran: from the bridge's model event sink, or from the transcript. It is the
    producer unless a response filter returned the response (`filtered`): the
    filter may have generated it itself, outside the sink, as an equal message
    that keeps the id. Then the latest such generation in the transcript is the
    producer, and `captured` only when the transcript has none and it has the
    response's message id (a filter that returned the generation's output
    unchanged, from a sink that withholds events).
    """
    if not filtered and captured is not None:
        return captured
    found = await _produced_event(bridge, message_id)
    if found is not None:
        return found
    if captured is not None and captured.output.message.id == message_id:
        return captured
    return None


async def _produced_event(
    bridge: AgentBridge, message_id: str | None
) -> "ModelEvent | None":
    from inspect_ai._sentinel._dispatch import produced_event

    async def lookup() -> "ModelEvent | None":
        return produced_event(message_id)

    return await _guarded(bridge, lookup)


def sentinel_tokens(
    bridge: AgentBridge, output: ModelOutput, checks: Sequence[SentinelCheck]
) -> tuple[ModelOutput, list[SentinelCheck]]:
    """Give each call handed to the scaffold its token as its id.

    `checks` are the `tool_result` checks for the calls in `output`, in order.
    Returns the output to hand to the scaffold (a copy, when any id changes),
    and the checks with their tokens.
    """
    issued = _result_checks(bridge).issue(checks)
    if all(check.token == check.handed.id for check in issued):
        return output, issued
    # a copy, as `output` may be the object the ModelEvent recorded
    output = output.model_copy(deep=True)
    for call, check in zip(output.message.tool_calls or [], issued):
        call.id = check.token or call.id
    return output, issued


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
        list(bridge.state.messages),
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

    The result is recorded as checked under the call's token, or, for a call
    that matched proposals of several calls (`candidates`, when the service
    can't tell which execution it is), under each of theirs, so the scaffold
    reporting it is not checked again. A host call no proposal accounts for has
    no token, so no result the scaffold reports can match it.
    """
    result = ChatMessageTool(
        content=content,
        tool_call_id=check.handed.id,
        function=check.call.function,
        error=error,
    )
    content_key = _content_key(result)
    executions = candidates or ([check] if check.token is not None else [])
    keys = [
        key
        for execution in executions
        for key in [
            mm3_hash(f"token:{execution.token}:{content_key}"),
            mm3_hash(f"call:{_call_key(execution.handed)}:{content_key}"),
        ]
    ] or [f"unproposed:{uuid()}"]
    await _result_checks(bridge).check_running(
        bridge, _Result(keys, check, result), output, truncated
    )


async def sentinel_tool_results(bridge: AgentBridge, input: list[ChatMessage]) -> None:
    if not checks_tool_calls():
        return
    result_checks = _result_checks(bridge)
    while True:
        claimed = result_checks.claim(input)
        if claimed.owned:
            try:
                await tg_collect(
                    [
                        partial(
                            result_checks.check,
                            bridge,
                            result,
                            _output(result.message),
                        )
                        for result in claimed.owned
                    ]
                )
            finally:
                for result in claimed.owned:
                    result_checks.release(result)
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
) -> None:
    from inspect_ai._sentinel._dispatch import sentinel_after_tool_call

    await _guarded(
        bridge,
        partial(
            sentinel_after_tool_call,
            check.message,
            check.message_id,
            check.call,
            result,
            output,
            truncated,
            check.viewer,
            check.history,
            check.producer,
            find_producer=not check.producer_resolved,
        ),
    )


async def _guarded(bridge: AgentBridge, run: Callable[[], Awaitable[T]]) -> T:
    # outcomes that end the sample go through the bridge, since a sandbox
    # bridge's service task can't raise them to the sample runner
    try:
        return await run()
    except TerminateSampleError as ex:
        bridge.request_terminate(str(ex))
    except SentinelFailure as ex:
        inner = inner_exception(ex.error)
        if isinstance(inner, LimitExceededError):
            raise inner from ex
        if isinstance(inner, TerminateSampleError):
            bridge.request_terminate(str(inner))
        bridge.request_fail(ex)
        raise
