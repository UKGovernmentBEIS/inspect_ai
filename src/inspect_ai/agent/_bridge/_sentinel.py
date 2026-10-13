import json
from collections import OrderedDict
from functools import partial
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
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
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
    history: list[ChatMessage]
    occurrence: str | None = None
    """The handed-over call's identity in the scaffold's conversation
    (`_occurrence`), or None for a host call no proposal accounts for."""


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
    occurrence: str


class _ResultChecks:
    """The `tool_result` checks for the results the scaffold reports.

    A call is identified by where it occurs in the scaffold's conversation: the
    conversation up to and including its assistant message, and its position in
    that message (`_occurrence`). Ids play no part, since a dialect may mint
    them anew (Google derives them from the call itself) or reuse them.

    Each distinct result is checked once, the first time a request carries it.
    A result is identified by its call's occurrence and by its content and
    error, so the same result repeated in later history is not checked again,
    while a changed result, or an identical result of another execution of the
    same call, is.

    A check takes its context from the proposal handed over at the call's
    occurrence. With none (one dropped beyond the cap, a call the bridge never
    handed over, a scaffold that rewrote the conversation before the call, or a
    result without a call), the result is checked with the conversation the
    request carries, and so usually with no model input, never with another
    call's.

    A host call's result is checked when the call executes, and that result,
    as delivered, is recorded as checked; any other content the scaffold
    reports for the call is checked here like a scaffold-run call's.

    Held by its bridge, since a failure's traceback references the bridge.
    """

    def __init__(self) -> None:
        self.proposals: OrderedDict[str, SentinelCheck] = OrderedDict()
        self.checked: set[str] = set()
        self.running: dict[str, anyio.Event] = {}
        self.failed: dict[str, Exception] = {}

    def add(self, check: SentinelCheck) -> None:
        if check.occurrence is None:
            return
        self.proposals[check.occurrence] = check
        self.proposals.move_to_end(check.occurrence)
        while len(self.proposals) > _MAX_PROPOSALS:
            self.proposals.popitem(last=False)
            warn_once(
                logger,
                f"More than {_MAX_PROPOSALS} bridged tool calls have been handed "
                "to the scaffold; the oldest was dropped, so the sentinel's "
                "tool_result check of a call handed over more than "
                f"{_MAX_PROPOSALS} calls ago sees only the conversation that "
                "carries its result, and usually no model input (never another "
                "call's).",
            )

    def claim(self, input: list[ChatMessage]) -> _Claimed:
        claimed = _Claimed([], [])
        keys: set[str] = set()
        calls: dict[str, _Call] = {}
        unanswered: dict[str, list[_Call]] = {}
        conversation = ""
        for index, message in enumerate(input):
            before = conversation
            conversation = _extend(conversation, message)
            if isinstance(message, ChatMessageAssistant):
                unanswered = {}
                for position, call in enumerate(message.tool_calls or []):
                    calls[call.id] = _Call(
                        call,
                        message.text,
                        index,
                        _occurrence(conversation, position),
                    )
                    unanswered.setdefault(call.id, []).append(calls[call.id])
            elif isinstance(message, ChatMessageTool):
                result_id = message.tool_call_id or ""
                found = (
                    unanswered[result_id].pop(0)
                    if unanswered.get(result_id)
                    else calls.get(result_id)
                )
                occurrence = (
                    found.occurrence
                    if found is not None
                    else mm3_hash(f"{before}:result:{result_id}:{message.function}")
                )
                key = _result_key(message, occurrence)
                if key in keys or key in self.checked:
                    continue
                if key in self.failed:
                    raise self.failed[key]
                if key in self.running:
                    claimed.waiting.append(self.running[key])
                    continue
                proposal = self.proposals.get(occurrence)
                if proposal is not None:
                    check = proposal
                else:
                    # the history ends with the call's assistant message, as on
                    # the native path; an orphan result has none
                    call = (
                        found.call
                        if found is not None
                        else ToolCall(
                            id=result_id, function=message.function or "", arguments={}
                        )
                    )
                    history = input[: found.position + 1 if found else index]
                    check = SentinelCheck(
                        call, call, None, found.text if found else "", history
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


def _extend(conversation: str, message: ChatMessage) -> str:
    """The identity of `conversation` (an `_extend` chain) followed by `message`.

    Built from what survives the scaffold's round trip: no ids (a dialect may
    mint new ones), no system messages (a scaffold may vary its system prompt
    from request to request), and of an assistant message with tool calls only
    its calls, as the scaffold must send those back as it received them.
    """
    if isinstance(message, ChatMessageSystem):
        return conversation
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        identity: Any = [
            "calls",
            [
                [call.function, _json_canonical(call.arguments)]
                for call in message.tool_calls
            ],
        ]
    elif isinstance(message, ChatMessageTool):
        error = message.error.message if message.error else None
        identity = ["tool", message.text, error]
    else:
        identity = [message.role, message.text]
    return mm3_hash(
        conversation + json.dumps(to_jsonable_python(identity, fallback=str))
    )


def _occurrence(conversation: str, position: int) -> str:
    """The call at `position` in the assistant message that ends `conversation`."""
    return mm3_hash(f"{conversation}:call:{position}")


def _json_canonical(value: Any) -> Any:
    # as `_json_equal`: 5 and 5.0 are the same argument, True and 1 are not
    value = to_jsonable_python(value, fallback=str)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _json_canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_json_canonical(item) for item in value]
    return value


def _result_key(result: ChatMessageTool, occurrence: str) -> str:
    # text is keyed as the content it stands for, as a dialect may report it
    # either way
    content = (
        [ContentText(text=result.content)]
        if isinstance(result.content, str)
        else result.content
    )
    return mm3_hash(
        json.dumps(
            to_jsonable_python([occurrence, content, result.error], fallback=str),
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
    history: list[ChatMessage],
) -> "Decision | None":
    from inspect_ai._sentinel._dispatch import sentinel_before_tool_call

    return await _guarded(
        bridge, partial(sentinel_before_tool_call, message, call, viewer, history)
    )


def sentinel_occurrences(
    input: list[ChatMessage], checks: Sequence[SentinelCheck]
) -> list[SentinelCheck]:
    """`checks` for the calls handed over in reply to `input`, with their occurrences.

    The scaffold's next request carries `input` followed by the response, so a
    call's occurrence there is `input`, then the calls as handed over, then the
    call's position among them.
    """
    conversation = ""
    for message in input:
        conversation = _extend(conversation, message)
    handed = ChatMessageAssistant(
        content="", tool_calls=[check.handed for check in checks]
    )
    conversation = _extend(conversation, handed)
    return [
        check._replace(occurrence=_occurrence(conversation, position))
        for position, check in enumerate(checks)
    ]


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
    return SentinelCheck(
        call, call, ToolDef(tool_fn).viewer, "", list(bridge.state.messages)
    )


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
    # a host call no proposal accounts for has no occurrence the scaffold could
    # report its result under
    occurrence = check.occurrence or f"unproposed:{uuid()}"
    await _result_checks(bridge).check(
        bridge, _Result(_result_key(result, occurrence), check, result), output
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
