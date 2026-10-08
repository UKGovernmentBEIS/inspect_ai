from collections import OrderedDict
from functools import partial
from typing import TYPE_CHECKING, Awaitable, Callable, NamedTuple, TypeVar
from weakref import WeakKeyDictionary

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
from inspect_ai.agent._bridge.sandbox.types import _json_equal
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError

if TYPE_CHECKING:
    from inspect_sentinel import Decision

T = TypeVar("T")

_MAX_PENDING_CALLS = 1000


class _PendingCall(NamedTuple):
    handed: ToolCall
    message: str
    call: ToolCall
    input: list[ChatMessage]
    history: list[ChatMessage]


_pending: "WeakKeyDictionary[AgentBridge, OrderedDict[str, _PendingCall]]" = (
    WeakKeyDictionary()
)


async def sentinel_tool_call(
    bridge: AgentBridge,
    message: str,
    call: ToolCall,
    input: list[ChatMessage],
    history: list[ChatMessage],
) -> "Decision | None":
    from inspect_ai._sentinel._dispatch import sentinel_before_tool_call

    return await _guarded(
        bridge,
        partial(sentinel_before_tool_call, message, call, None, history, input=input),
    )


def track_sentinel_calls(
    bridge: AgentBridge,
    message: str,
    calls: list[tuple[ToolCall, ToolCall]],
    input: list[ChatMessage],
    history: list[ChatMessage],
) -> None:
    pending = _pending.setdefault(bridge, OrderedDict())
    for handed, call in calls:
        pending[call.id] = _PendingCall(handed, message, call, input, history)
        while len(pending) > _MAX_PENDING_CALLS:
            pending.popitem(last=False)


async def sentinel_host_tool_result(
    bridge: AgentBridge,
    call_id: str,
    content: str | list[Content],
    output: ToolResult,
) -> None:
    pending = _take(bridge, call_id)
    if pending is not None:
        result = ChatMessageTool(
            content=content, tool_call_id=call_id, function=pending.call.function
        )
        await _tool_result(bridge, pending, result, output)


async def sentinel_tool_results(bridge: AgentBridge, input: list[ChatMessage]) -> None:
    if active_sentinel() is None:
        return
    results: list[tuple[_PendingCall, ChatMessageTool]] = []
    calls: dict[str, ToolCall] = {}
    for message in input:
        if isinstance(message, ChatMessageAssistant):
            calls.update({call.id: call for call in message.tool_calls or []})
        elif isinstance(message, ChatMessageTool) and message.tool_call_id is not None:
            pending = _take(bridge, message.tool_call_id) or _take_matching(
                bridge, calls.get(message.tool_call_id)
            )
            if pending is not None:
                results.append((pending, message))
    if results:
        await tg_collect(
            [
                partial(_tool_result, bridge, pending, result, _output(result))
                for pending, result in results
            ]
        )


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


def discard_sentinel_call(bridge: AgentBridge, call_id: str) -> None:
    _take(bridge, call_id)


def _take(bridge: AgentBridge, call_id: str) -> _PendingCall | None:
    pending = _pending.get(bridge)
    return pending.pop(call_id, None) if pending is not None else None


def _take_matching(bridge: AgentBridge, call: ToolCall | None) -> _PendingCall | None:
    # a dialect whose calls carry no id (Google) mints new ids when the scaffold
    # sends a call back, so match the call as handed over instead
    pending = _pending.get(bridge)
    if pending is None or call is None:
        return None
    for call_id, entry in pending.items():
        if entry.handed.function == call.function and _json_equal(
            to_jsonable_python(entry.handed.arguments, fallback=str),
            call.arguments,
        ):
            return pending.pop(call_id)
    return None


async def _tool_result(
    bridge: AgentBridge,
    pending: _PendingCall,
    result: ChatMessageTool,
    output: ToolResult,
) -> None:
    from inspect_ai._sentinel._dispatch import sentinel_after_tool_call

    await _guarded(
        bridge,
        partial(
            sentinel_after_tool_call,
            pending.message,
            pending.call,
            result,
            output,
            None,
            pending.history,
            input=pending.input,
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
