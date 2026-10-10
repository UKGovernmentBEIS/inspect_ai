import json
from collections import OrderedDict
from functools import partial
from itertools import count
from logging import getLogger
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    NamedTuple,
    Sequence,
    TypeVar,
)

import anyio
from pydantic_core import to_jsonable_python
from shortuuid import uuid

from inspect_ai._sentinel._context import SentinelFailure, active_sentinel
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
from inspect_ai.agent._bridge.sandbox.types import _json_equal
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool._tool import Tool, ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallError, ToolCallViewer
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError

if TYPE_CHECKING:
    from inspect_sentinel import Decision

logger = getLogger(__name__)

T = TypeVar("T")

_MAX_PROPOSALS = 1000


class SentinelCheck(NamedTuple):
    handed: ToolCall
    call: ToolCall
    viewer: ToolCallViewer | None
    message: str
    input: list[ChatMessage]
    history: list[ChatMessage]


class _Result(NamedTuple):
    key: str
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

    Each distinct result is checked once, the first time a request carries it.
    A result is identified by its call's id, function and arguments and by its
    content and error, so the same result repeated in later history is not
    checked again, while a changed result or a later call reusing an id is.

    A check takes its context from the call's proposal, found by id or, for a
    dialect that mints new ids (like Google), by function and arguments. With
    no proposal (e.g. one dropped beyond the cap, or a result without an id),
    the result is checked with what the request carries.

    A host call's result is checked when the call executes, and that result,
    as delivered, is recorded as checked; any other content the scaffold
    reports for the call is checked here like a scaffold-run call's.

    Held by its bridge, since a failure's traceback references the bridge.
    """

    def __init__(self) -> None:
        self.proposals: OrderedDict[int, SentinelCheck] = OrderedDict()
        self.checked: set[str] = set()
        self.running: dict[str, anyio.Event] = {}
        self.failed: dict[str, Exception] = {}
        self._sequence = count()

    def add(self, check: SentinelCheck) -> None:
        self.proposals[next(self._sequence)] = check
        while len(self.proposals) > _MAX_PROPOSALS:
            self.proposals.popitem(last=False)
            warn_once(
                logger,
                f"More than {_MAX_PROPOSALS} bridged tool calls have been handed "
                "to the scaffold; the oldest was dropped, so the sentinel's "
                "tool_result check of a call handed over more than "
                f"{_MAX_PROPOSALS} calls ago sees only the conversation that "
                "carries its result.",
            )

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
                proposal: SentinelCheck | None = None
                if found is None:
                    proposal = self._proposal(result_id, None) if result_id else None
                    call = (
                        proposal.handed
                        if proposal is not None
                        else ToolCall(
                            id=result_id, function=message.function or "", arguments={}
                        )
                    )
                else:
                    call = found.call
                key = _result_key(message, call)
                if key in keys or key in self.checked:
                    continue
                if key in self.failed:
                    raise self.failed[key]
                if key in self.running:
                    claimed.waiting.append(self.running[key])
                    continue
                if found is not None:
                    proposal = self._proposal(result_id, call)
                if proposal is not None:
                    check = proposal
                else:
                    context = input[: found.position if found else index]
                    check = SentinelCheck(
                        call, call, None, found.text if found else "", context, context
                    )
                keys.add(key)
                claimed.owned.append(_Result(key, check, message))
        for result in claimed.owned:
            self.running[result.key] = anyio.Event()
        return claimed

    async def check(
        self, bridge: AgentBridge, result: _Result, output: ToolResult
    ) -> None:
        try:
            await _tool_result(bridge, result.check, result.message, output)
        except Exception as ex:
            self.failed[result.key] = ex
            raise
        self.checked.add(result.key)

    def release(self, result: _Result) -> None:
        # a check that did not finish is claimed again by the next request
        # carrying its result
        self.running.pop(result.key).set()

    def _proposal(self, result_id: str, call: ToolCall | None) -> SentinelCheck | None:
        # newest first; a known call needs a proposal of the same call, and
        # prefers one with its id
        proposals = list(reversed(self.proposals.values()))
        if call is None:
            return next((p for p in proposals if p.handed.id == result_id), None)
        same = [p for p in proposals if _same_call(p.handed, call)]
        return next(
            (p for p in same if p.handed.id == result_id),
            same[0] if same else None,
        )


def _same_call(handed: ToolCall, call: ToolCall) -> bool:
    return handed.function == call.function and _json_equal(
        to_jsonable_python(handed.arguments, fallback=str), call.arguments
    )


def _result_key(result: ChatMessageTool, call: ToolCall) -> str:
    # text is keyed as the content it stands for, as a dialect may report it
    # either way
    content = (
        [ContentText(text=result.content)]
        if isinstance(result.content, str)
        else result.content
    )
    return mm3_hash(
        json.dumps(
            to_jsonable_python(
                [
                    call.id,
                    call.function,
                    call.arguments,
                    content,
                    result.error,
                ],
                fallback=str,
            ),
            sort_keys=True,
        )
    )


def _result_checks(bridge: AgentBridge) -> _ResultChecks:
    if bridge._sentinel_results is None:
        bridge._sentinel_results = _ResultChecks()
    return bridge._sentinel_results


async def sentinel_tool_call(
    bridge: AgentBridge,
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    input: list[ChatMessage],
    history: list[ChatMessage],
) -> "Decision | None":
    from inspect_ai._sentinel._dispatch import sentinel_before_tool_call

    return await _guarded(
        bridge,
        partial(sentinel_before_tool_call, message, call, viewer, history, input=input),
    )


def sentinel_model_input(
    message: ChatMessageAssistant, history: list[ChatMessage]
) -> list[ChatMessage]:
    # a filter that generated the output itself sent the model its own input,
    # which only its ModelEvent records
    from inspect_ai._sentinel._dispatch import _model_input

    return _model_input((message.tool_calls or [])[0], history)


def track_sentinel_calls(bridge: AgentBridge, checks: Sequence[SentinelCheck]) -> None:
    result_checks = _result_checks(bridge)
    for check in checks:
        result_checks.add(check)


def sentinel_unproposed_host_check(
    bridge: AgentBridge, tool: str, arguments: dict[str, Any], tool_fn: Tool
) -> SentinelCheck | None:
    # a host call no proposal accounts for is checked with the conversation the
    # bridge last saw, as a scaffold-reported result without a proposal is
    if active_sentinel() is None:
        return None
    call = ToolCall(id=f"call_{tool}_{uuid()[:8]}", function=tool, arguments=arguments)
    context = list(bridge.state.messages)
    return SentinelCheck(call, call, ToolDef(tool_fn).viewer, "", context, context)


async def sentinel_host_tool_result(
    bridge: AgentBridge,
    check: SentinelCheck,
    content: str | list[Content],
    output: ToolResult,
    error: ToolCallError | None = None,
) -> None:
    result = ChatMessageTool(
        content=content,
        tool_call_id=check.handed.id,
        function=check.call.function,
        error=error,
    )
    await _result_checks(bridge).check(
        bridge, _Result(_result_key(result, check.handed), check, result), output
    )


async def sentinel_tool_results(bridge: AgentBridge, input: list[ChatMessage]) -> None:
    if active_sentinel() is None:
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
) -> None:
    from inspect_ai._sentinel._dispatch import sentinel_after_tool_call

    await _guarded(
        bridge,
        partial(
            sentinel_after_tool_call,
            check.message,
            check.call,
            result,
            output,
            check.viewer,
            check.history,
            input=check.input,
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
