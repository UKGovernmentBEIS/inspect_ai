from collections import Counter, OrderedDict
from functools import partial
from itertools import count
from logging import getLogger
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple, Sequence, TypeVar
from weakref import WeakKeyDictionary

import anyio
from pydantic_core import to_jsonable_python

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
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._bridge.sandbox.types import _json_equal
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallError, ToolCallViewer
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError

if TYPE_CHECKING:
    from inspect_sentinel import Decision

logger = getLogger(__name__)

T = TypeVar("T")

_MAX_PENDING_CALLS = 1000


class SentinelCheck(NamedTuple):
    handed: ToolCall
    call: ToolCall
    viewer: ToolCallViewer | None
    message: str
    input: list[ChatMessage]
    history: list[ChatMessage]


class _Invocation:
    def __init__(self, check: SentinelCheck) -> None:
        self.check: SentinelCheck | None = check
        self.running: anyio.Event | None = None
        self.done = False
        self.error: Exception | None = None

    def release(self) -> None:
        if self.running is not None:
            running, self.running = self.running, None
            running.set()

    def finish(self, error: Exception | None) -> None:
        self.check = None
        self.done = True
        self.error = error
        self.release()


class _Claimed(NamedTuple):
    owned: list[tuple[_Invocation, ChatMessageTool]]
    waiting: list[anyio.Event]


class _ResultChecks:
    """The `tool_result` checks for calls whose results the scaffold reports.

    A result is matched to one invocation: the n-th result carrying an id in a
    conversation is the result of the n-th invocation bound to that id, so a
    result already seen never takes the check of a later call. A new result is
    bound to the oldest unbound call handed over with its id or, for an id no
    handed call had (a dialect that mints new ids, like Google), with its
    function and arguments.
    """

    def __init__(self) -> None:
        self.unbound: OrderedDict[int, _Invocation] = OrderedDict()
        self.bound: dict[str, list[_Invocation | None]] = {}
        self.handed_ids: set[str] = set()
        self._sequence = count()

    def add(self, check: SentinelCheck) -> None:
        self.unbound[next(self._sequence)] = _Invocation(check)
        while len(self.unbound) > _MAX_PENDING_CALLS:
            self.unbound.popitem(last=False)
            warn_once(
                logger,
                f"More than {_MAX_PENDING_CALLS} bridged tool calls run by the "
                "scaffold are awaiting their results; the oldest was dropped, so "
                "the sentinel's tool_result check may be skipped for calls handed "
                f"to the scaffold more than {_MAX_PENDING_CALLS} calls ago.",
            )

    def claim(self, input: list[ChatMessage]) -> _Claimed:
        calls: dict[str, ToolCall] = {}
        occurrences: Counter[str] = Counter()
        bound: list[tuple[_Invocation, ChatMessageTool]] = []
        for message in input:
            if isinstance(message, ChatMessageAssistant):
                calls.update({call.id: call for call in message.tool_calls or []})
            elif isinstance(message, ChatMessageTool) and message.tool_call_id:
                result_id = message.tool_call_id
                occurrence = occurrences[result_id]
                occurrences[result_id] += 1
                slots = self.bound.setdefault(result_id, [])
                if occurrence < len(slots):
                    invocation = slots[occurrence]
                else:
                    invocation = self._take(result_id, calls.get(result_id))
                    slots.append(invocation)
                if invocation is not None:
                    bound.append((invocation, message))

        claimed = _Claimed([], [])
        for invocation, message in bound:
            if invocation.error is not None:
                raise invocation.error
            if invocation.running is not None:
                claimed.waiting.append(invocation.running)
            elif not invocation.done:
                claimed.owned.append((invocation, message))
        for invocation, _ in claimed.owned:
            invocation.running = anyio.Event()
        return claimed

    def _take(self, result_id: str, call: ToolCall | None) -> _Invocation | None:
        by_id = result_id in self.handed_ids
        for key, invocation in self.unbound.items():
            assert invocation.check is not None
            handed = invocation.check.handed
            if by_id:
                matches = handed.id == result_id
            else:
                matches = (
                    call is not None
                    and handed.function == call.function
                    and _json_equal(
                        to_jsonable_python(handed.arguments, fallback=str),
                        call.arguments,
                    )
                )
            if matches:
                del self.unbound[key]
                return invocation
        return None


_result_checks: "WeakKeyDictionary[AgentBridge, _ResultChecks]" = WeakKeyDictionary()


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


def track_sentinel_calls(
    bridge: AgentBridge, checks: Sequence[SentinelCheck], granted: Sequence[bool]
) -> None:
    result_checks = _result_checks.setdefault(bridge, _ResultChecks())
    for check, host in zip(checks, granted):
        result_checks.handed_ids.add(check.handed.id)
        # a host call is checked against its execution grant, never against a
        # result the scaffold reports
        if not host:
            result_checks.add(check)


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
    await _tool_result(bridge, check, result, output)


async def sentinel_tool_results(bridge: AgentBridge, input: list[ChatMessage]) -> None:
    if active_sentinel() is None:
        return
    result_checks = _result_checks.get(bridge)
    if result_checks is None:
        return
    while True:
        claimed = result_checks.claim(input)
        if claimed.owned:
            try:
                await tg_collect(
                    [
                        partial(_claimed_result, bridge, invocation, result)
                        for invocation, result in claimed.owned
                    ]
                )
            finally:
                # an interrupted check is claimed again by the next request
                # carrying its result
                for invocation, _ in claimed.owned:
                    invocation.release()
        if not claimed.waiting:
            return
        for running in claimed.waiting:
            await running.wait()


async def _claimed_result(
    bridge: AgentBridge, invocation: _Invocation, result: ChatMessageTool
) -> None:
    assert invocation.check is not None
    try:
        await _tool_result(bridge, invocation.check, result, _output(result))
    except Exception as ex:
        invocation.finish(ex)
        raise
    invocation.finish(None)


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
