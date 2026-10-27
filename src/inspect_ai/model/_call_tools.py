import inspect
import json
import string
import types
import typing
from collections.abc import Collection
from copy import copy, deepcopy
from dataclasses import is_dataclass, replace
from datetime import date, datetime, time
from enum import EnumMeta
from logging import getLogger
from textwrap import dedent
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

if TYPE_CHECKING:
    from inspect_ai.approval import ApprovalPolicy
    from inspect_ai.review import ReviewPolicy

import anyio
import yaml
from anyio.streams.memory import MemoryObjectSendStream
from pydantic import BaseModel, TypeAdapter
from typing_extensions import is_typeddict

from inspect_ai._sentinel._context import SentinelFailure, checks_tool_calls
from inspect_ai._sentinel._scope import sentinel_scope
from inspect_ai._util._async import raise_unwrapped
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.dateutil import datetime_from_iso_format_safe
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.format import format_function_call
from inspect_ai._util.json import exceeds_max_depth, json_equal, to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai._util.trace import trace_action
from inspect_ai._util.working import (
    known_work,
    sample_clock,
    sample_working_time_since,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool import Tool, ToolCall, ToolError, ToolInfo
from inspect_ai.tool._tool import (
    ToolApprovalError,
    ToolParsingError,
    ToolResult,
    ToolSource,
    tool_result_content,
)
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallError
from inspect_ai.tool._tool_canonical import tool_canonical_arguments
from inspect_ai.tool._tool_def import ToolDef, tool_def_fields, tool_defs
from inspect_ai.tool._tool_info import parse_docstring
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util import OutputLimitExceededError
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._json import dataclass_fields
from inspect_ai.util._limit import LimitExceededError, apply_limits
from inspect_ai.util._sandbox.environment import SandboxUnavailableError
from inspect_ai.util._sandbox.events import SandboxTimeoutError
from inspect_ai.util._span import AGENT_SPAN_TYPE, span

from ._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from ._generate_config import active_generate_config

logger = getLogger(__name__)


TOOL_CALLS_FAIL_FAST = "tool_calls_fail_fast"
"""Assistant message metadata key naming tools whose calls form a fail-fast batch.

The value is a list of tool names. Within that assistant message, calls to a
named tool run serially and stop at the first tool error: each later call to
the same tool is not executed and is answered with
`Not executed: an earlier <tool> action in this turn failed.` Providers set it
when the model API defines batch semantics for a tool (Anthropic's computer
toolset); `execute_tools` reads it. Calls to other tools are unaffected.
"""


def _fail_fast_tools(message: ChatMessageAssistant) -> set[str]:
    value = (message.metadata or {}).get(TOOL_CALLS_FAIL_FAST)
    if isinstance(value, list):
        return {name for name in value if isinstance(name, str)}
    return set()


class ExecuteToolsResult(NamedTuple):
    """Result from executing tools in the last assistant message.

    In conventional tool calling scenarios there will be only a list
    of `ChatMessageTool` appended and no-output. However, if there
    are `handoff()` tools (used in multi-agent systems) then other
    messages may be appended and an `output` may be available as well.
    """

    messages: list[ChatMessage]
    """Messages added to conversation."""

    output: ModelOutput | None = None
    """Model output if a generation occurred within the conversation."""


def _sentinel_exception(ex: SentinelFailure) -> Exception:
    # A limit keeps its meaning. Any other sentinel error must fail the sample
    # rather than become a tool error the model sees, so it stays wrapped through
    # enclosing agents' tool calls until the sample unwraps it.
    inner = inner_exception(ex.error)
    if isinstance(inner, (LimitExceededError, TerminateSampleError)):
        return inner
    return ex


async def execute_tools(
    messages: list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
    max_output: int | None = None,
    approval: list["ApprovalPolicy"] | None = None,
    review: list["ReviewPolicy"] | None = None,
) -> ExecuteToolsResult:
    """Perform tool calls in the last assistant message.

    Args:
       messages: Current message list
       tools (list[Tool]): Available tools
       max_output (int | None): Maximum output length (in bytes).
          Defaults to max_tool_output from active GenerateConfig
          (16 * 1024 by default).
       approval (list[ApprovalPolicy] | None): Approval policies to
          use for tool calls within this execution. Temporarily
          replaces any active approval policies for the duration
          of the call.
       review (list[ReviewPolicy] | None): Review policies to use for
          the results of tool calls within this execution. Temporarily
          replaces any active review policies for the duration of the
          call.

    Returns:
       Messages added to the conversation and final model output (if any)
    """
    from contextlib import nullcontext

    from inspect_ai.approval._apply import approval as approval_context
    from inspect_ai.review._apply import review as review_context

    approval_cm = approval_context(approval) if approval else nullcontext()
    review_cm = review_context(review) if review else nullcontext()
    with approval_cm, review_cm:
        return await _execute_tools_impl(messages, tools, max_output)


async def _execute_tools_impl(
    messages: list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
    max_output: int | None = None,
) -> ExecuteToolsResult:
    message = messages[-1]
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        from inspect_ai.event._tool import ToolEvent
        from inspect_ai.log._transcript import transcript

        tool_calls = message.tool_calls
        tdefs = await tool_defs(tools)

        async def call_tool_task(
            call: ToolCall,
            event: ToolEvent,
            conversation: list[ChatMessage],
            send_stream: MemoryObjectSendStream[
                tuple[ExecuteToolsResult, ToolEvent, Exception | None]
            ],
            on_review_cancelled: Callable[[ExecuteToolsResult, ToolEvent], None],
        ) -> None:
            result: ToolResult = ""
            messages: list[ChatMessage] = []
            output: ModelOutput | None = None
            agent: str | None = None
            agent_span_id: str | None = None
            tool_error: ToolCallError | None = None
            tool_exception: Exception | None = None
            executed_call: ToolCall | None = None

            def note_executed_call(executed: ToolCall) -> None:
                """Track entry into the tool body, including approver modifications.

                A tool body can raise the same errors as pre-execution validation,
                so the exception type cannot tell us whether the call executed.
                """
                nonlocal executed_call
                executed_call = executed

            # Track this tool call on the active sample's execution observer
            # so an intervention producer (ACP today) can snapshot the
            # in-flight tool id into InterruptEvent. No-op when no observer
            # is installed (no producer attached) or when no sample is active.
            from inspect_ai.agent._channel import null_execution_observer
            from inspect_ai.log._samples import sample_active

            _sample = sample_active()
            _observer = (
                _sample.execution_observer
                if _sample is not None
                else null_execution_observer()
            )

            try:
                try:
                    with _observer.track_tool_call(call.id, event), known_work():
                        called = await call_tool(
                            tdefs,
                            message.text,
                            message.id,
                            call,
                            event,
                            conversation,
                            on_execute=note_executed_call,
                        )
                        result = called.result
                        messages = called.messages
                        output = called.output
                        agent = called.agent
                        agent_span_id = called.agent_span_id
                # unwrap exception group
                except Exception as ex:
                    raise_unwrapped(ex, inner_exception(ex))

            except SentinelFailure as ex:
                tool_exception = _sentinel_exception(ex)
            except Exception as ex:
                mapped = tool_call_error(ex, call.function)
                if mapped is not None:
                    tool_error = mapped.error
                    if mapped.result is not None:
                        result = mapped.result
                elif isinstance(ex, ValueError):
                    # pre-existing: a ValueError other than the null-byte case
                    # escapes the per-call handler rather than being captured
                    raise
                else:
                    tool_exception = ex

            content, truncated = resolve_tool_content(
                result,
                call.function,
                _tool_max_output(tdefs, call.function, max_output),
            )

            # create event (`call_tool` records an approver's modified arguments
            # on `event`)
            result_event = ToolEvent(
                id=call.id,
                function=call.function,
                arguments=event.arguments,
                result=content,
                truncated=truncated,
                view=event.view,
                error=tool_error,
                agent=agent,
                agent_span_id=agent_span_id,
            )

            # the result as the model will see it
            tool_message = ChatMessageTool(
                content=cast(list[Content], content),
                tool_call_id=call.id,
                function=call.function,
                error=tool_error,
            )
            execution_result = ExecuteToolsResult(
                messages=[tool_message] + messages,
                output=output,
            )
            if tool_exception is None and executed_call is not None:
                try:
                    with _observer.track_tool_call(call.id, event):
                        await _apply_tool_review(
                            tdefs,
                            message.text,
                            message.id,
                            executed_call,
                            tool_message,
                            result,
                            truncated,
                            conversation,
                        )
                except anyio.get_cancelled_exc_class():
                    on_review_cancelled(execution_result, result_event)
                    raise
                except SentinelFailure as ex:
                    tool_exception = _sentinel_exception(ex)
                except Exception as ex:
                    tool_exception = ex

            # yield message and event
            async with send_stream:
                await send_stream.send(
                    (
                        execution_result,
                        result_event,
                        tool_exception,
                    )
                )

        StreamItem = tuple[ExecuteToolsResult, ToolEvent, Exception | None]

        # Tools whose calls in this message form an ordered batch that stops
        # at the first failure (see TOOL_CALLS_FAIL_FAST).
        fail_fast_tools = _fail_fast_tools(message)

        # Determine each call's parallel eligibility from its ToolDef.
        # Unknown tools default to serial. A fail-fast tool runs serially
        # regardless: its later calls must not start until an earlier one has
        # succeeded.
        def is_parallel(call: ToolCall) -> bool:
            if call.function in fail_fast_tools:
                return False
            tdef = next((t for t in tdefs if t.name == call.function), None)
            return bool(tdef and tdef.parallel)

        # Partition tool_calls into ordered execution stages. Consecutive
        # parallel-safe calls coalesce into one concurrent stage; each
        # serial call is its own one-element stage and acts as a barrier
        # that preserves the model's declared ordering between stateful
        # and stateless calls.
        parallel_flags = [is_parallel(c) for c in tool_calls]
        stages: list[list[int]] = []
        i = 0
        while i < len(parallel_flags):
            if parallel_flags[i]:
                start = i
                while i < len(parallel_flags) and parallel_flags[i]:
                    i += 1
                stages.append(list(range(start, i)))
            else:
                stages.append([i])
                i += 1

        # Fail-fast tools (by name) whose earlier call in this message failed
        # with a tool error: their remaining calls are not executed.
        halted_functions: set[str] = set()

        result_messages: list[ChatMessage] = []
        result_output: ModelOutput | None = None

        for stage in stages:
            # Pre-create pending events and start times so they reflect the
            # moment this stage actually starts. (The tool transcript event
            # itself is recorded inside call_tool by call_tool_task; the start
            # time lets us compute working time.)
            stage_events: dict[int, ToolEvent] = {}
            waiting_starts: dict[int, float] = {}
            stage_results: dict[int, StreamItem | None] = {}
            for idx in stage:
                call = tool_calls[idx]
                waiting_starts[idx] = sample_clock()
                stage_events[idx] = ToolEvent(
                    id=call.id,
                    function=call.function,
                    arguments=call.arguments,
                    view=call.view,
                    pending=True,
                )
                stage_results[idx] = None

            # Calls to a halted tool are not executed. Synthesise their
            # results now (the post-stage splice below places them in
            # declared order) and finalise their events.
            skipped: set[int] = {
                idx for idx in stage if tool_calls[idx].function in halted_functions
            }
            for idx in sorted(skipped):
                call = tool_calls[idx]
                event = stage_events[idx]
                tool_message = ChatMessageTool(
                    content="",
                    function=call.function,
                    tool_call_id=call.id,
                    error=ToolCallError(
                        "cancelled",
                        f"Not executed: an earlier {call.function} action in "
                        "this turn failed.",
                    ),
                )
                skipped_event = ToolEvent(
                    id=call.id,
                    function=call.function,
                    arguments=call.arguments,
                    result=tool_result_content(tool_message.content),
                    truncated=None,
                    view=call.view,
                    error=tool_message.error,
                )
                stage_results[idx] = (
                    ExecuteToolsResult(messages=[tool_message], output=None),
                    skipped_event,
                    None,
                )
                event._set_result(
                    result=skipped_event.result,
                    truncated=skipped_event.truncated,
                    error=skipped_event.error,
                    working_time=sample_working_time_since(waiting_starts[idx]),
                    agent=None,
                    failed=None,
                    message_id=tool_message.id,
                )
                transcript()._event(event)
                transcript().info(
                    f"Tool call '{call.function}' was not executed because an "
                    "earlier call to it in this turn failed."
                )

            async def run_one(
                idx: int,
                events: dict[int, ToolEvent],
                results: dict[int, StreamItem | None],
                waiting_starts: dict[int, float],
            ) -> None:
                call = tool_calls[idx]
                event = events[idx]
                waiting_start = waiting_starts[idx]
                review_cancellation: TerminateSampleError | None = None

                def record_review_cancellation(
                    result: ExecuteToolsResult, result_event: ToolEvent
                ) -> None:
                    """Preserve an executed call when its unfinished review is cancelled.

                    Cancellation cannot undo execution. Retain the actual result
                    for log readers, and prevent an operator's per-call cancel
                    from resuming the sample without a review decision. Outer
                    cancellation still propagates with its original reason.
                    """
                    nonlocal review_cancellation
                    review_cancellation = TerminateSampleError(
                        "Tool result review was cancelled before a decision."
                    )
                    results[idx] = (result, result_event, review_cancellation)
                    event._set_result(
                        result=result_event.result,
                        truncated=result_event.truncated,
                        error=result_event.error,
                        working_time=sample_working_time_since(waiting_start),
                        agent=result_event.agent,
                        failed=None,
                        message_id=result.messages[0].id,
                        agent_span_id=result_event.agent_span_id,
                    )
                    transcript()._event_updated(event)
                    transcript().info(
                        f"Review of tool call '{call.function}' ({call.id}) was "
                        "cancelled before a decision; its result was preserved."
                    )

                send_stream, receive_stream = anyio.create_memory_object_stream[
                    StreamItem
                ]()
                try:
                    # Per-call task group nested inside the stage's outer
                    # task group. Its cancel_scope is exposed via
                    # event._set_cancel_fn so an operator-driven cancel of
                    # this specific call doesn't disturb its siblings.
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(
                            call_tool_task,
                            call,
                            event,
                            messages,
                            send_stream,
                            record_review_cancellation,
                        )
                        event._set_cancel_fn(tg.cancel_scope.cancel)
                        async with receive_stream:
                            item = await receive_stream.receive()
                            results[idx] = item
                            result, result_event, call_exception = item

                            # Finalise this call's event now so its
                            # `completed`/`working_time` reflect when *this*
                            # call actually finished, not when the whole
                            # stage exits. Fast siblings of slow tools would
                            # otherwise look as slow as the slowest call.
                            event._set_result(
                                result=result_event.result,
                                truncated=result_event.truncated,
                                error=result_event.error,
                                working_time=sample_working_time_since(waiting_start),
                                agent=result_event.agent,
                                failed=True if call_exception else None,
                                message_id=(
                                    result.messages[0].id
                                    if result and result.messages
                                    else None
                                ),
                                agent_span_id=result_event.agent_span_id,
                            )
                            transcript()._event_updated(event)

                            # An unhandled exception captured by call_tool_task
                            # needs to be re-raised here so the surrounding
                            # outer task group cancels in-flight siblings.
                            if call_exception is not None:
                                raise call_exception
                except anyio.EndOfStream:
                    # call_tool_task closed send_stream without sending;
                    # leave the post-task-group block below to detect and
                    # finalise the cancellation.
                    pass

                if review_cancellation is not None:
                    raise review_cancellation

                # If this call's per-call CancelScope was cancelled via
                # `event._cancel()` (operator-initiated for *this* call),
                # the CancelScope swallowed its own CancelledError and we
                # exited the task group cleanly. Synthesise and finalise
                # the cancellation now so `completed`/`working_time`
                # reflect when the cancel hit — not stage end. A synthetic
                # StreamItem is stashed in `results` so the post-stage
                # loop splices the cancellation message in declared order.
                #
                # When the outer task group cancelled this call instead
                # (sibling raised), the CancelledError propagates out of
                # `run_one` and this block is skipped; the post-stage loop
                # handles the sibling-cancellation synthesis with its
                # own messaging.
                if results[idx] is None and event.cancelled:
                    op_tool_message = ChatMessageTool(
                        content="",
                        function=call.function,
                        tool_call_id=call.id,
                        error=ToolCallError(
                            "timeout", "Command timed out before completing."
                        ),
                    )
                    op_result_event = ToolEvent(
                        id=call.id,
                        function=call.function,
                        arguments=event.arguments,
                        result=tool_result_content(op_tool_message.content),
                        truncated=None,
                        view=event.view,
                        error=op_tool_message.error,
                    )
                    results[idx] = (
                        ExecuteToolsResult(messages=[op_tool_message], output=None),
                        op_result_event,
                        None,
                    )
                    event._set_result(
                        result=op_result_event.result,
                        truncated=op_result_event.truncated,
                        error=op_result_event.error,
                        working_time=sample_working_time_since(waiting_start),
                        agent=op_result_event.agent,
                        # Operator-cancel preserves pre-existing serial
                        # semantics: failed=None, the "timeout" error
                        # type is the only marker.
                        failed=None,
                        message_id=op_tool_message.id,
                        agent_span_id=op_result_event.agent_span_id,
                    )
                    # call_tool records the pending event only after
                    # approval. If the cancel hit before that, append it
                    # now (both _event and _event_updated notify
                    # subscribers via _process_event, so we do one or
                    # the other — never both).
                    if event not in transcript().events:
                        transcript()._event(event)
                    else:
                        transcript()._event_updated(event)
                    transcript().info(
                        f"Tool call '{call.function}' was cancelled by operator."
                    )

            stage_exception: Exception | None = None
            try:
                async with anyio.create_task_group() as outer_tg:
                    for idx in stage:
                        if idx in skipped:
                            continue
                        outer_tg.start_soon(
                            run_one,
                            idx,
                            stage_events,
                            stage_results,
                            waiting_starts,
                        )
            except Exception as ex:
                stage_exception = ex

            # Splice results into `result_messages` in declared order so the
            # message list matches the order of tool_calls (Anthropic and
            # other providers require tool_result blocks to match tool_use
            # block order). Events are already finalised — successes and
            # exceptions inside run_one's success path, operator cancels
            # inside run_one's EndOfStream path — except for siblings
            # cancelled by an unhandled exception in another stage member,
            # which we synthesise and finalise here.
            for idx in stage:
                call = tool_calls[idx]
                event = stage_events[idx]
                waiting_start = waiting_starts[idx]
                stream_item = stage_results[idx]

                if stream_item is None:
                    # No StreamItem means the call neither completed nor was
                    # operator-cancelled (run_one's EndOfStream branch would
                    # have synthesised one). The only remaining cause is the
                    # outer task group cancelling this call when another
                    # sibling raised an unhandled exception.
                    tool_message = ChatMessageTool(
                        content="",
                        function=call.function,
                        tool_call_id=call.id,
                        error=ToolCallError(
                            "cancelled",
                            "Tool call cancelled because a parallel sibling "
                            "tool call raised an exception.",
                        ),
                    )
                    cancellation_event = ToolEvent(
                        id=call.id,
                        function=call.function,
                        arguments=event.arguments,
                        result=tool_result_content(tool_message.content),
                        truncated=None,
                        view=event.view,
                        error=tool_message.error,
                    )
                    transcript().info(
                        f"Tool call '{call.function}' was cancelled because "
                        "a parallel sibling tool call raised an exception."
                    )
                    result_messages.append(tool_message)

                    event._set_result(
                        result=cancellation_event.result,
                        truncated=cancellation_event.truncated,
                        error=cancellation_event.error,
                        working_time=sample_working_time_since(waiting_start),
                        agent=cancellation_event.agent,
                        failed=True,
                        message_id=tool_message.id,
                        agent_span_id=cancellation_event.agent_span_id,
                    )
                    # call_tool records the pending event only after
                    # approval. If the sibling cancel hit before that,
                    # append it now (both _event and _event_updated
                    # notify subscribers via _process_event, so we do
                    # one or the other — never both).
                    if event not in transcript().events:
                        transcript()._event(event)
                    else:
                        transcript()._event_updated(event)
                else:
                    # Event was finalised in run_one (success, exception, or
                    # operator cancel). Just splice the (possibly synthetic)
                    # messages in declared order.
                    result, _, _ = stream_item
                    if result is not None:
                        result_messages.extend(result.messages)
                        if result.output is not None:
                            result_output = result.output

            # A tool error from a fail-fast tool halts that tool's remaining
            # calls in this message (an unhandled exception is re-raised
            # below and ends execution outright).
            for idx in stage:
                stream_item = stage_results[idx]
                if (
                    idx in skipped
                    or stream_item is None
                    or tool_calls[idx].function not in fail_fast_tools
                ):
                    continue
                result, _, _ = stream_item
                if any(
                    isinstance(m, ChatMessageTool) and m.error is not None
                    for m in result.messages[:1]
                ):
                    halted_functions.add(tool_calls[idx].function)

            # If anything in the stage raised, re-raise after updating the
            # events so the transcript captures partial state cleanly.
            if stage_exception is not None:
                raise_unwrapped(stage_exception, inner_exception(stage_exception))

        # return tool messages
        return ExecuteToolsResult(result_messages, result_output)

    else:
        return ExecuteToolsResult([])


class CalledTool(NamedTuple):
    """Outcome of `call_tool()`."""

    result: ToolResult
    messages: list[ChatMessage]
    """Further messages produced by the call (a handoff's sub-agent conversation)."""
    output: ModelOutput | None
    agent: str | None
    agent_span_id: str | None


async def call_tool(
    tools: list[ToolDef],
    message: str,
    message_id: str | None,
    call: ToolCall,
    event: BaseModel,
    conversation: list[ChatMessage],
    on_execute: Callable[[ToolCall], None] | None = None,
) -> CalledTool:
    from inspect_ai.agent._handoff import AgentTool
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import transcript

    # dodge circular import
    assert isinstance(event, ToolEvent)

    # this function is responsible for transcript events so that it can
    # put them in the right enclosure (e.g. handoff/agent/tool). This
    # means that if we throw early we need to do the enclosure when raising.
    async def record_pending_tool_event() -> None:
        async with span(name=call.function, type="tool"):
            transcript()._event(event)

    async def record_tool_parsing_error(error: str) -> Exception:
        await record_pending_tool_event()
        return ToolParsingError(error)

    async def revalidated_tool_call(
        selected: ToolCall, tool_def: ToolDef
    ) -> ValidatedToolCall:
        # a modify runs on canonical arguments, like the model's call
        canonical_arguments = tool_canonical_arguments(tool_def.tool)
        if canonical_arguments is not None:
            selected = replace(
                selected, arguments=canonical_arguments(selected.arguments)
            )
        # the event records the modified call, so a failure is logged with the
        # arguments that caused it (the model's proposal stays in the
        # ModelEvent and the ApprovalEvent)
        event.arguments = selected.arguments
        event.view = None
        try:
            validated = modified_tool_call(selected, tool_def)
        except ToolParsingError as ex:
            raise await record_tool_parsing_error(ex.message)
        except ToolApprovalError:
            await record_pending_tool_event()
            raise
        # the selected call may carry a view of other arguments (a modify built
        # with `replace()`), so it gets the view rendered for the event
        event.view = tool_call_view(deepcopy(validated.call), tools)
        return validated._replace(
            call=replace(validated.call, view=deepcopy(event.view))
        )

    def shown_to_callbacks(decided: ToolCall) -> ToolCall:
        # a copy the next approve decision must match; the event records it,
        # so a later callback cannot change what the log says ran
        shown = deepcopy(decided)
        event.arguments = shown.arguments
        return shown

    # if there was an error parsing the ToolCall, raise that
    if call.parse_error:
        raise await record_tool_parsing_error(call.parse_error)

    # providers that deliver arguments as an already-parsed dict never go
    # through parse_tool_call, so the nesting bound is enforced here as well
    if _exceeds_max_depth(call.arguments):
        raise await record_tool_parsing_error(
            f"Error parsing tool call arguments: {_max_depth_parse_error()}"
        )

    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        raise await record_tool_parsing_error(f"Tool {call.function} not found")

    model_call = call
    canonical_arguments = tool_canonical_arguments(tool_def.tool)
    if canonical_arguments is not None:
        call = replace(call, arguments=canonical_arguments(call.arguments))

    # approvers and sentinel monitors see the validated call, so an invalid
    # call is never presented for approval
    try:
        validated = validated_tool_call(call, tool_def)
    except ToolParsingError as ex:
        raise await record_tool_parsing_error(ex.message)
    overseen = validated.call is not call
    if overseen:
        # under oversight the event and the call show the call as approvers see it
        event.view = tool_call_view(deepcopy(validated.call), tools)
        validated.call.view = deepcopy(event.view)
    call, arguments = validated
    # without oversight the event records the model's arguments, as on main
    shown = shown_to_callbacks(call if overseen else model_call)

    # if we have a tool approver, apply it now
    from inspect_ai.approval._apply import (
        apply_tool_approval,
        modified_function_error,
    )

    approved, approval = await apply_tool_approval(
        message, call, tool_def.viewer, conversation
    )
    if not approved:
        await record_pending_tool_event()
        if approval and approval.decision == "terminate":
            message = "Tool call approver requested termination."
            raise TerminateSampleError(message)
        else:
            raise ToolApprovalError(approval.explanation if approval else None)
    if (
        approval is not None
        and approval.decision == "modify"
        and approval.modified is not None
    ):
        error = modified_function_error(shown, approval.modified) or (
            _modified_id_error("An approver", shown, approval.modified)
        )
        if error is not None:
            await record_pending_tool_event()
            raise RuntimeError(error)
        call, arguments = await revalidated_tool_call(approval.modified, tool_def)
        shown = shown_to_callbacks(call)
    elif approval is not None and _changed_in_place(call, shown):
        await record_pending_tool_event()
        raise ToolApprovalError(_CHANGED_IN_PLACE)

    if checks_tool_calls():
        from inspect_ai._sentinel._dispatch import (
            apply_sentinel_decision,
            sentinel_before_tool_call,
        )

        try:
            decision = await sentinel_before_tool_call(
                message, message_id, call, tool_def.viewer, conversation
            )
            modified = apply_sentinel_decision(decision, call)
            selected = decision is not None and decision.action == "modify"
            if not selected and _changed_in_place(call, shown):
                raise ToolApprovalError(_CHANGED_IN_PLACE)
        except (SentinelFailure, ToolApprovalError, TerminateSampleError):
            await record_pending_tool_event()
            raise
        if selected:
            if modified.function != shown.function:
                await record_pending_tool_event()
                raise RuntimeError(
                    _SENTINEL_MODIFIED_FUNCTION.format(
                        modified.function, shown.function
                    )
                )
            id_error = _modified_id_error("A sentinel monitor", shown, modified)
            if id_error is not None:
                await record_pending_tool_event()
                raise RuntimeError(id_error)
            call, arguments = await revalidated_tool_call(modified, tool_def)
            shown_to_callbacks(call)

    # call the tool (curried handoff values and omitted defaults are the
    # developer's objects, so only the call's own arguments are traced)
    traced = arguments
    if isinstance(tool_def.tool, AgentTool):
        traced = {
            k: v
            for k, v in arguments.items()
            if k in call.arguments and k not in tool_def.tool.kwargs
        }
    with trace_action(
        logger, "Tool Call", format_function_call(tool_def.name, traced, width=1000)
    ):
        if isinstance(tool_def.tool, AgentTool):
            async with span(tool_def.tool.name, type="handoff"):
                async with span(name=call.function, type="tool"):
                    transcript()._event(event)
                    if on_execute is not None:
                        on_execute(call)
                    handoff_result = await agent_handoff(
                        tool_def, call, arguments, conversation
                    )
                    return CalledTool(*handoff_result, None)

        # normal tool call
        else:
            async with span(name=call.function, type="tool"):
                transcript()._event(event)
                if on_execute is not None:
                    on_execute(call)
                with sentinel_scope("tool"):
                    result: ToolResult = await tool_def.tool(**arguments)
                agent_span_id = getattr(tool_def.tool, "agent_span_id", None)
                return CalledTool(result, [], None, None, agent_span_id)


_CHANGED_IN_PLACE = (
    "An approver or sentinel monitor changed the tool call in place, so the call "
    "was not run. To change a call, return a modify decision with a new ToolCall."
)


_SENTINEL_MODIFIED_FUNCTION = (
    "A sentinel monitor returned a modified call to '{}' for a call to '{}'. A "
    "'modify' decision may change only the arguments of a tool call, not the "
    "function called."
)


def _modified_id_error(who: str, shown: ToolCall, modified: ToolCall) -> str | None:
    """Error for a native `modify` decision that changes the call's id, else `None`.

    The tool message and event keep the model's id, so a modified call that ran
    under another id would not match them.
    """
    if modified.id == shown.id:
        return None
    return (
        f"{who} returned a modified call with id '{modified.id}' for the call "
        f"with id '{shown.id}'. A 'modify' decision may change only the "
        "arguments of a tool call, not its id."
    )


def _changed_in_place(call: ToolCall, shown: ToolCall) -> bool:
    """Whether a callback changed `call` in place since it was `shown`.

    Approvers and sentinel monitors change a call only by returning a modify
    decision, so a call they approve must still be the one they were shown.
    """
    return (
        call.id != shown.id
        or call.function != shown.function
        or not json_equal(call.arguments, shown.arguments)
    )


async def _apply_tool_review(
    tools: list[ToolDef],
    message: str,
    message_id: str | None,
    call: ToolCall,
    result: ChatMessageTool,
    output: ToolResult,
    truncated: tuple[int, int] | None,
    conversation: list[ChatMessage],
) -> None:
    """Give the active review policies and sentinel the executed call's result.

    Only calls that actually ran are reviewed (the caller checks this): a call
    rejected at the call stage or failed by argument parsing produced no result,
    and the error the model receives is its feedback.

    Raises:
        TerminateSampleError: A reviewer or the sentinel requested termination.
    """
    from inspect_ai.review._apply import apply_tool_review

    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    review = await apply_tool_review(
        message,
        call,
        result,
        output,
        tool_def.viewer if tool_def else None,
        conversation,
    )
    if review is not None and review.decision == "terminate":
        raise TerminateSampleError("Tool result reviewer requested termination.")

    if checks_tool_calls():
        from inspect_ai._sentinel._dispatch import sentinel_after_tool_call

        await sentinel_after_tool_call(
            message,
            message_id,
            call,
            result,
            output,
            truncated,
            tool_def.viewer if tool_def else None,
            conversation,
        )


async def agent_handoff(
    tool_def: ToolDef,
    call: ToolCall,
    arguments: dict[str, Any],
    conversation: list[ChatMessage],
) -> tuple[ToolResult, list[ChatMessage], ModelOutput | None, str]:
    from inspect_ai.agent._agent import AgentState, agent_display_name
    from inspect_ai.agent._handoff import AgentTool

    # alias agent tool and get agent name (display name, consistent with the
    # agent's transcript spans and the transfer_to_<name> tool the model sees)
    agent_tool = cast(AgentTool, tool_def.tool)
    agent_name = agent_display_name(agent_tool.agent)

    # copy list
    agent_conversation = copy(conversation)

    # remove other tool calls from the assistant message so the
    # conversation remains valid (the model may have called multiple
    # tools in parallel and we won't be handling the other calls)
    last_message = agent_conversation[-1]
    if isinstance(last_message, ChatMessageAssistant) and last_message.tool_calls:
        agent_conversation[-1] = agent_conversation[-1].model_copy(
            update=dict(
                tool_calls=[
                    tool_call
                    for tool_call in last_message.tool_calls
                    if tool_call.id == call.id
                ]
            )
        )

    # ammend the conversation with a ChatMessageTool to indicate
    # to the downstream agent that we satisfied the call
    tool_result = f"Successfully transferred to {agent_name}."
    agent_conversation.append(
        ChatMessageTool(
            content=tool_result,
            tool_call_id=call.id,
            function=call.function,
        )
    )

    def is_transferred_to_tool_response(message: ChatMessage) -> bool:
        return isinstance(message, ChatMessageTool) and message.tool_call_id == call.id

    # run input filter if we have one
    if agent_tool.input_filter is not None:
        agent_conversation = await agent_tool.input_filter(agent_conversation)

    # if our ChatMessageTool boundary was removed (e.g. due to using the `remove_tools`
    # or `content_only` filter) then add a ChatMessageUser boundary.
    if not is_transferred_to_tool_response(agent_conversation[-1]):
        agent_conversation.append(ChatMessageUser(content=tool_result))

    def is_agent_conversation_boundary(message: ChatMessage) -> bool:
        if is_transferred_to_tool_response(message):
            return True
        elif isinstance(message, ChatMessageUser):
            if isinstance(message.content, str):
                return message.content == tool_result
            elif len(message.content) > 0 and isinstance(
                message.content[0], ContentText
            ):
                return message.content[0].text == tool_result
            else:
                return False

        else:
            return False

    # remove system messages (as they can refer to tools or other special
    # instructions that don't apply to the sub-agent)
    agent_conversation = [
        m for m in agent_conversation if not isinstance(m, ChatMessageSystem)
    ]

    # run the agent with limits
    limit_error: LimitExceededError | None = None
    agent_state = AgentState(messages=copy(agent_conversation))
    try:
        # The agent_tool's limits will be applied multiple times if the agent is handed
        # off to multiple times which is not supported, so create a copy of each limit.
        with apply_limits(deepcopy(agent_tool.limits)):
            async with span(name=agent_name, type=AGENT_SPAN_TYPE):
                agent_state = await agent_tool.agent(agent_state, **arguments)
    except LimitExceededError as ex:
        limit_error = ex

    # find the demaraction line of 'new' messages
    agent_conversation_boundary_indices = [
        i
        for i, msg in enumerate(agent_state.messages)
        if is_agent_conversation_boundary(msg)
    ]
    if agent_conversation_boundary_indices:
        start_idx = agent_conversation_boundary_indices[-1] + 1
        agent_state.messages = agent_state.messages[start_idx:]

    # determine which messages are new and return only those (but exclude new
    # system messages as they an internal matter for the handed off to agent.
    # also, inject the agent's name as a prefix in assistant messages
    conversation_message_ids = [message.id for message in agent_conversation]
    agent_messages: list[ChatMessage] = []
    for m in agent_state.messages:
        if m.id not in conversation_message_ids:
            if isinstance(m, ChatMessageAssistant):
                m = prepend_agent_name(m, agent_name)
            if not isinstance(m, ChatMessageSystem):
                agent_messages.append(m)

    # run output filter if we have one
    if agent_tool.output_filter is not None:
        agent_messages = await agent_tool.output_filter(agent_messages)

    if limit_error is not None:
        agent_messages.append(
            ChatMessageUser(
                content=(
                    f"The {agent_name} exceeded its {limit_error.type} limit of "
                    f"{limit_error.limit_str}."
                )
            )
        )
    # if we end with an assistant message then add a user message
    # so that the calling agent carries on
    elif len(agent_messages) == 0 or isinstance(
        agent_messages[-1], ChatMessageAssistant
    ):
        agent_messages.append(
            ChatMessageUser(content=f"The {agent_name} agent has completed its work.")
        )

    return (tool_result, agent_messages, agent_state.output, agent_name)


def prepend_agent_name(
    message: ChatMessageAssistant, agent_name: str
) -> ChatMessageAssistant:
    if isinstance(message.content, str):
        return message.model_copy(
            update=dict(content=f"[{agent_name}] {message.content}")
        )
    else:
        content = copy(message.content)
        for i in range(0, len(content)):
            if isinstance(content[i], ContentText):
                text = cast(ContentText, content[i]).text
                if text:
                    content[i] = content[i].model_copy(
                        update=dict(text=f"[{agent_name}] {text}")
                    )
                break
        return message.model_copy(update=dict(content=content))


async def resolve_tools(
    tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource,
) -> list[Tool | ToolDef | ToolInfo]:
    # resolve top level tool source
    if isinstance(tools, ToolSource):
        tools = await tools.tools()

    # resolve tool sources
    resolved_tools: list[Tool | ToolDef | ToolInfo] = []
    for tool in tools:
        if isinstance(tool, ToolSource):
            source_tools = await tool.tools()
            resolved_tools.extend(source_tools)
        else:
            resolved_tools.append(tool)

    return resolved_tools


class PreparedTools(NamedTuple):
    tdefs: list[ToolDef]
    base_tools: list[ToolInfo]


def _tool_info_from_tdef(tdef: ToolDef, *, own_parameters: bool) -> ToolInfo:
    parameters = (
        tdef.parameters.model_copy(deep=True) if own_parameters else tdef.parameters
    )
    return ToolInfo(
        name=tdef.name,
        description=tdef.description,
        parameters=parameters,
        options=tdef.options,
    )


async def prepare_tools(
    tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource,
) -> PreparedTools:
    resolved_tools = await resolve_tools(tools)
    tdefs: list[ToolDef] = []
    base_tools: list[ToolInfo] = []

    for tool in resolved_tools:
        if isinstance(tool, ToolInfo):
            base_tools.append(tool.model_copy(deep=True))
        elif isinstance(tool, ToolDef):
            tdefs.append(tool)
            base_tools.append(_tool_info_from_tdef(tool, own_parameters=True))
        else:
            fields = tool_def_fields(tool)
            tdef = ToolDef(
                tool,
                name=fields.name,
                description=fields.description,
                parameters=fields.parameters,
                parallel=fields.parallel,
                viewer=fields.viewer,
                model_input=fields.model_input,
                max_output=fields.max_output,
                options=fields.options,
            )
            tdefs.append(tdef)
            base_tools.append(
                ToolInfo(
                    name=fields.name,
                    description=fields.description,
                    parameters=fields.parameters,
                    options=fields.options,
                )
            )

    return PreparedTools(tdefs=tdefs, base_tools=base_tools)


def copy_tools_info(tools: Sequence[ToolInfo]) -> list[ToolInfo]:
    return [tool.model_copy(deep=True) for tool in tools]


def snapshot_tools_for_event(
    call_tools: Sequence[ToolInfo], base_tools: Sequence[ToolInfo]
) -> list[ToolInfo]:
    base_tools_by_name = {tool.name: tool for tool in base_tools}
    snapshots: list[ToolInfo] = []
    for call_tool in call_tools:
        base_tool = base_tools_by_name.get(call_tool.name)
        parameters = (
            base_tool.parameters
            if base_tool and call_tool.parameters == base_tool.parameters
            else call_tool.parameters.model_copy(deep=True)
        )
        snapshot = call_tool.model_copy(deep=False)
        snapshot.parameters = parameters
        snapshot.options = deepcopy(call_tool.options)
        snapshots.append(snapshot)
    return snapshots


def tools_info_equal(left: Sequence[ToolInfo], right: Sequence[ToolInfo]) -> bool:
    if len(left) != len(right):
        return False
    return all(left_tool == right_tool for left_tool, right_tool in zip(left, right))


def get_tools_info(
    tools: Sequence[Tool | ToolDef | ToolInfo],
) -> list[ToolInfo]:
    tools_info: list[ToolInfo] = []
    for tool in tools:
        if isinstance(tool, ToolInfo):
            tools_info.append(tool)
        else:
            if isinstance(tool, Tool):
                tool = ToolDef(tool)
            tools_info.append(
                ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                    options=tool.options,
                )
            )
    return tools_info


def type_hint_includes_none(type_hint: Type[Any] | None) -> bool:
    origin = get_origin(type_hint)

    if origin in {Union, UnionType}:
        return type(None) in get_args(type_hint)
    elif origin is Optional:
        return True
    return False


def tool_params(
    input: dict[str, Any], func: Callable[..., Any], skip: Collection[str] = ()
) -> dict[str, Any]:
    """Convert a tool call's arguments to the parameters of `func`.

    Args:
        input: The arguments, as the model supplied them.
        func: The tool (or agent) function.
        skip: Parameters the caller supplies itself, which are neither
            converted nor required.
    """
    # parse function typeinfo
    signature = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = inspect.getdoc(func)

    # if the function takes **kwargs: Any then just pass the tool arguments through
    if "kwargs" in type_hints and type_hints["kwargs"] == Any:
        return {name: value for name, value in input.items() if name not in skip}

    # build params
    params: dict[str, Any] = {}
    named_params: set[str] = set()
    var_keyword: inspect.Parameter | None = None
    for param_name, param in signature.parameters.items():
        # *args can't be passed by name, so tool arguments never fill it
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue

        # **kwargs receives the arguments that no named parameter takes
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            var_keyword = param
            continue

        named_params.add(param_name)
        if param_name in skip:
            continue

        # get type hint (fallback to docstring as required)
        type_hint = param_type_hint(param_name, type_hints, docstring)

        # error if there is no type_hint
        if type_hint is None:
            raise ValueError(f"No type annotation available for parameter {param_name}")

        # yield parameter (fail if not passed and there is no default)
        if param_name in input:
            params[param_name] = _converted_param(
                param_name, type_hint, input.get(param_name)
            )
        elif param.default is not inspect.Parameter.empty:
            params[param_name] = param.default
        elif type_hint_includes_none(type_hint):
            params[param_name] = None
        else:
            raise ToolParsingError(
                f"Required parameter {param_name} not provided to tool call."
            )

    # pass the remaining arguments (e.g. ones declared by an explicit tool
    # schema) through to **kwargs, converted using its annotation or
    # docstring type if present
    if var_keyword is not None:
        kwargs_type: Any = (
            param_type_hint(var_keyword.name, type_hints, docstring) or Any
        )
        for name, value in input.items():
            if name not in named_params:
                params[name] = _converted_param(name, kwargs_type, value)

    return params


def _converted_param(name: str, type_hint: Type[Any], value: Any) -> Any:
    # conversion runs before approval, so a value it cannot convert (a bad
    # date or enum value, a failing constructor) goes back to the model
    try:
        return tool_param(type_hint, value)
    except ToolParsingError:
        raise
    except Exception as ex:
        detail = str(ex) or type(ex).__name__
        raise ToolParsingError(
            f"Unable to convert argument '{name}' for the tool: {detail}"
        ) from ex


def param_type_hint(
    param_name: str, type_hints: dict[str, Type[Any]], docstring: str | None
) -> Type[Any] | None:
    # prefer the annotation
    if param_name in type_hints:
        return type_hints[param_name]

    # as a fallback try to parse it from the docstring (a documented type
    # that can't be resolved is an error rather than missing type info)
    docstring_info = parse_docstring(docstring, param_name)
    if "docstring_type" in docstring_info:
        import builtins

        type_hint: Type[Any] | None = getattr(
            builtins, docstring_info["docstring_type"], None
        )
        if type_hint is None:
            raise ValueError(f"No type annotation available for parameter {param_name}")
        return type_hint

    return None


class ValidatedToolCall(NamedTuple):
    """Outcome of `validated_tool_call()`."""

    call: ToolCall
    """The call approvers, sentinel monitors and viewers see."""

    arguments: dict[str, Any]
    """The arguments the tool receives."""


def validated_tool_call(call: ToolCall, tool_def: ToolDef) -> ValidatedToolCall:
    """Validate and convert a call's arguments before it is approved.

    The arguments are checked against the tool's schema and converted to the
    tool's parameter types. While approval or a sentinel is active, the
    returned call holds the converted arguments serialized as JSON, and the
    returned arguments are rebuilt from that JSON, which must serialize back
    to itself and equal the converted arguments. Otherwise the call is
    returned unchanged. See
    `design/tool-approval-arguments.md`.

    Raises:
        ToolParsingError: The arguments fail the schema or cannot be
            converted, or (while approval or a sentinel is active) cannot be
            serialized, nest deeper than the arguments the model may send, do
            not survive the log writing and reading them unchanged, or do not
            rebuild to the same JSON and value.
    """
    validation_errors = validate_tool_input(call.arguments, tool_def.parameters)
    if validation_errors:
        raise ToolParsingError(validation_errors)

    if not _tool_calls_overseen():
        return ValidatedToolCall(call, _rebuilt_arguments(call.arguments, tool_def))

    converted = _rebuilt_arguments(call.arguments, tool_def)
    shown = replace(
        call, arguments=_serialized_converted(call.arguments, converted, tool_def)
    )
    for name, value in shown.arguments.items():
        if _exceeds_max_depth({name: value}):
            raise ToolParsingError(
                f"Argument '{name}' cannot be shown to approvers or monitors: as "
                "converted for the tool and serialized, it exceeds the maximum "
                f"supported nesting depth of {MAX_TOOL_CALL_ARGUMENTS_DEPTH}."
            )
    _check_logged_unchanged(shown)
    try:
        changed = _changed_on_rebuild(shown.arguments, tool_def)
        rebuilt = _rebuilt_arguments(shown.arguments, tool_def)
    except ToolParsingError as ex:
        raise ToolParsingError(
            "The arguments cannot be shown to approvers or monitors: as "
            "converted for the tool and serialized, they do not convert back. "
            f"{ex.message}"
        ) from ex
    if changed is None:
        # serialization can hide or mask a value (a secret, an excluded field,
        # private attributes), so the tool must get the value the model's
        # arguments convert to, not only the same JSON
        changed = _changed_from(shown.arguments, converted, rebuilt)
    if changed is not None:
        raise ToolParsingError(
            f"Argument '{changed}' cannot be shown to approvers or monitors: as "
            "converted for the tool and serialized, it does not convert back to "
            "the same value."
        )
    return ValidatedToolCall(shown, rebuilt)


def modified_tool_call(selected: ToolCall, tool_def: ToolDef) -> ValidatedToolCall:
    """Validate an approver's or sentinel's modified call, which runs as selected.

    The selected arguments are the JSON the tool's arguments are rebuilt
    from, so they must serialize back to exactly that JSON: a modify gives
    every argument and field in full, as shown.

    Raises:
        ToolParsingError: The modified arguments are invalid.
        ToolApprovalError: Rebuilding an argument for the tool changes it.
    """
    validation_errors = validate_tool_input(selected.arguments, tool_def.parameters)
    if validation_errors:
        raise ToolParsingError(validation_errors)

    changed = _changed_on_rebuild(selected.arguments, tool_def)
    if changed is not None:
        raise ToolApprovalError(
            f"The modified value for '{changed}' changes when it is converted "
            "for the tool, so the call was not run. A modify decision must give "
            "the full call as shown, including any defaults it fills in."
        )
    return ValidatedToolCall(selected, _rebuilt_arguments(selected.arguments, tool_def))


def _tool_calls_overseen() -> bool:
    """Whether an approval policy or a sentinel will see tool calls."""
    from inspect_ai.approval._apply import have_tool_approval

    return have_tool_approval() or checks_tool_calls()


def _rebuilt_arguments(arguments: dict[str, Any], tool_def: ToolDef) -> dict[str, Any]:
    """The tool's arguments converted from a call's, with curried handoff values.

    Conversion gets a copy of the call's arguments, since a constructor (a
    validator, `__post_init__`) can change its input in place.
    """
    from inspect_ai.agent._handoff import AgentTool

    arguments = deepcopy(arguments)
    if isinstance(tool_def.tool, AgentTool):
        # agent_handoff passes the real `state`, and the developer's curried
        # arguments are Python values that go to the agent as given
        curried = tool_def.tool.kwargs
        converted = tool_params(
            arguments, tool_def.tool.agent, skip={"state", *curried}
        )
        return {**converted, **curried}
    return tool_params(arguments, tool_def.tool)


def _serialized_arguments(
    arguments: dict[str, Any], tool_def: ToolDef
) -> dict[str, Any]:
    """A call's arguments as converted for the tool, serialized as JSON."""
    return _serialized_converted(
        arguments, _rebuilt_arguments(arguments, tool_def), tool_def
    )


def _serialized_converted(
    arguments: dict[str, Any], converted: dict[str, Any], tool_def: ToolDef
) -> dict[str, Any]:
    """A call's arguments, already converted for the tool, serialized as JSON.

    Only the arguments the call gives are serialized: parameters it leaves
    out get their Python defaults when the arguments are rebuilt, and curried
    handoff values are not part of the call.
    """
    from inspect_ai.agent._handoff import AgentTool

    curried = tool_def.tool.kwargs if isinstance(tool_def.tool, AgentTool) else {}
    return {
        name: _serialized(name, converted[name])
        for name in arguments
        if name in converted and name not in curried
    }


def _check_logged_unchanged(call: ToolCall) -> None:
    """Check that the event writer stores each argument unchanged.

    Each argument is written in the call as events write it and read back, so
    a value the log cannot hold (a non-finite number becomes null, an
    unpaired surrogate escaped text) reloads as something else, and one it
    cannot read back (an integer over Python's digit limit) fails.

    Raises:
        ToolParsingError: An argument reloads changed, or writing or reading
            it failed.
    """
    for name, value in call.arguments.items():
        try:
            logged = json.loads(
                to_json_str_safe(replace(call, arguments={name: value}))
            )["arguments"]
            unchanged = name in logged and json_equal(logged[name], value)
            detail = ""
        except Exception as ex:
            unchanged = False
            detail = f" Writing it and reading it back failed ({ex})."
        if not unchanged:
            raise ToolParsingError(
                f"Argument '{name}' cannot be shown to approvers or monitors: as "
                "converted for the tool and serialized, it holds a value the log "
                "cannot store unchanged (such as inf, NaN or an unpaired "
                f"surrogate).{detail}"
            )


def _changed_on_rebuild(arguments: dict[str, Any], tool_def: ToolDef) -> str | None:
    """The first argument that does not serialize back to itself when rebuilt."""
    rebuilt = _serialized_arguments(arguments, tool_def)
    for name in [*arguments, *(name for name in rebuilt if name not in arguments)]:
        if name not in rebuilt or not json_equal(rebuilt[name], arguments.get(name)):
            return name
    return None


def _changed_from(
    shown: dict[str, Any], converted: dict[str, Any], rebuilt: dict[str, Any]
) -> str | None:
    """The first shown argument whose rebuilt value does not equal its converted one.

    Only shown arguments are compared: omitted parameters and curried handoff
    values are not part of the shown call and reach the tool as they are.

    Raises:
        ToolParsingError: Comparing an argument's values raised.
    """
    for name in shown:
        try:
            equal = name in rebuilt and bool(rebuilt[name] == converted[name])
        except Exception as ex:
            raise ToolParsingError(
                f"Argument '{name}' cannot be shown to approvers or monitors: "
                f"comparing it with its value as rebuilt failed ({ex!r})."
            ) from ex
        if not equal:
            return name
    return None


_JSON_VALUE = TypeAdapter[Any](Any)


def _serialized(name: str, value: Any) -> Any:
    """An argument value as JSON, with models dumped by alias and without computed fields."""
    try:
        return _JSON_VALUE.dump_python(
            value,
            mode="json",
            by_alias=True,
            exclude_computed_fields=True,
        )
    except Exception as ex:
        raise ToolParsingError(
            f"Argument '{name}' cannot be shown to approvers or monitors: "
            f"serializing it failed ({ex})."
        ) from ex


def tool_param(type_hint: Type[Any], input: Any) -> Any:
    origin = get_origin(type_hint)
    args = get_args(type_hint)

    if origin is None:
        if type_hint == typing.Any:
            return input
        elif type_hint in [int, str, float, bool]:
            try:
                return type_hint(input)
            except (ValueError, TypeError):
                raise ToolParsingError(
                    f"Unable to convert '{input}' to {type_hint.__name__}"
                )
        elif type_hint == datetime:
            if input.endswith("Z"):
                # convert trailing Z to +00:00
                input = input[:-1] + "+00:00"
            return datetime_from_iso_format_safe(input)
        elif type_hint == date:
            return date.fromisoformat(input)
        elif type_hint == time:
            return time.fromisoformat(input)
        elif is_typeddict(type_hint):
            typeddict_data: dict[str, Any] = {}
            annotations = get_type_hints(type_hint)
            for name, hint in annotations.items():
                typeddict_data[name] = tool_param(hint, input.get(name))
            return typeddict_data
        elif is_dataclass(type_hint):
            dataclass_data: dict[str, Any] = {}
            for name, (_, field_type) in dataclass_fields(type_hint).items():
                dataclass_data[name] = tool_param(field_type, input.get(name))
            return type_hint(**dataclass_data)
        elif issubclass(type_hint, BaseModel):
            return type_hint(**input)
        elif isinstance(type_hint, EnumMeta):
            return type_hint(input)
        else:
            return input
    elif origin is list or origin is List:
        if args:
            return [tool_param(args[0], x) for x in input]
        else:
            return input
    elif origin is set or origin is Set:
        if args:
            return {tool_param(args[0], x) for x in input}
        else:
            return set(input)
    elif origin is tuple or origin is Tuple:
        if args:
            return tuple([tool_param(args[0], x) for x in input])
        else:
            return tuple(input)
    elif origin is dict or origin is Dict:
        if args and len(args) > 1:
            return {k: tool_param(args[1], v) for k, v in input.items()}
        else:
            return input
    elif origin is Union or origin is types.UnionType:
        if args[1] is type(None) and input is not None:
            return tool_param(args[0], input)
        else:
            return input
    else:
        return input


class MappedToolCallError(NamedTuple):
    """A tool-execution exception mapped to the error the model/human sees.

    Returned from tool_call_error(); None means the exception is
    unexpected. Native tool calls (`execute_tools`) and the sandbox agent
    bridge's host tools (`call_tool`) both classify with it and fail the
    sample on an unexpected exception. `classify_tool_exception()` adapts
    it for the human agent tool path (`human_cli(tools=...)`, #3053), whose
    caller is not part of this module.
    """

    error: ToolCallError
    result: ToolResult | None = None


def tool_call_error(ex: Exception, function: str) -> MappedToolCallError | None:
    """Map a tool-execution exception to the error the caller reports.

    Callers must normalize exception groups (inner_exception()) first.
    Control-flow exceptions are classified where they have a tool-error
    rendering (limits) — callers with propagation semantics re-raise after
    recording. Unexpected exceptions (including non-embedded-null-byte
    ValueErrors) return None: this function is policy-free, and each
    caller applies its own disposition.

    Args:
        ex: The (normalized) exception raised by tool execution.
        function: Tool function name (used in messages).

    Returns:
        MappedToolCallError with the error (and any partial result, e.g.
        truncated output from a sandbox timeout, or None if there is no
        partial result), or None if the exception is unexpected.
    """
    if isinstance(ex, TimeoutError):
        return MappedToolCallError(
            error=ToolCallError("timeout", "Command timed out before completing."),
            result=ex.truncated_output
            if isinstance(ex, SandboxTimeoutError) and ex.truncated_output
            else None,
        )
    elif isinstance(ex, UnicodeDecodeError):
        return MappedToolCallError(
            error=ToolCallError(
                "unicode_decode",
                f"Error decoding bytes to {ex.encoding}: {ex.reason}",
            )
        )
    elif isinstance(ex, ValueError) and "embedded null byte" in str(ex):
        # CPython's subprocess module raises ValueError("embedded null byte")
        # when a command or argument string contains '\x00'. Surface it as
        # a tool error so the model can recover instead of crashing the sample.
        # (Other ValueErrors are unexpected — callers apply their own policy.)
        return MappedToolCallError(
            error=ToolCallError(
                "parsing",
                f"An argument to tool '{function}' contained an embedded null byte.",
            )
        )
    elif isinstance(ex, SandboxUnavailableError):
        # Preserve the tool loop's existing non-terminal behavior while
        # surfacing sandbox unavailability as a failed tool call. Evals
        # that need it to be terminal can enforce that policy in their
        # agent logic.
        return MappedToolCallError(error=ToolCallError("sandbox_unavailable", str(ex)))
    elif isinstance(ex, PermissionError):
        err = f"{ex.strerror or str(ex)}."
        if isinstance(ex.filename, str):
            err = f"{err} Filename '{ex.filename}'."
        return MappedToolCallError(error=ToolCallError("permission", err))
    elif isinstance(ex, FileNotFoundError):
        if isinstance(ex.filename, str):
            err = f"File '{ex.filename}' was not found."
        else:
            err = ex.strerror or str(ex)
        return MappedToolCallError(error=ToolCallError("file_not_found", err))
    elif isinstance(ex, IsADirectoryError):
        err = f"{ex.strerror or str(ex)}."
        if isinstance(ex.filename, str):
            err = f"{err} Filename '{ex.filename}'."
        return MappedToolCallError(error=ToolCallError("is_a_directory", err))
    elif isinstance(ex, OutputLimitExceededError):
        return MappedToolCallError(
            error=ToolCallError(
                "limit",
                f"The tool exceeded its output limit of {ex.limit_str}.",
            ),
            # Note the sentinel here is "" (not None): a limit-truncated
            # result of zero bytes is still a known ("no output") partial
            # result, distinct from "no partial result available" (None).
            result=ex.truncated_output or "",
        )
    elif isinstance(ex, LimitExceededError):
        return MappedToolCallError(
            error=ToolCallError(
                "limit",
                f"The tool exceeded its {ex.type} limit of {ex.limit_str}.",
            )
        )
    elif isinstance(ex, ToolParsingError):
        return MappedToolCallError(error=ToolCallError("parsing", ex.message))
    elif isinstance(ex, ToolApprovalError):
        return MappedToolCallError(error=ToolCallError("approval", ex.message))
    elif isinstance(ex, ToolError):
        return MappedToolCallError(error=ToolCallError("unknown", ex.message))
    else:
        return None


class ClassifiedToolException(NamedTuple):
    """A tool-execution exception classified as an expected tool failure.

    Compatibility adapter for #3053's human agent tool path, which passes
    `result` straight into `resolve_tool_content()` and needs the "no
    partial result" sentinel to be `""`, not `None`. `tool_call_error()`
    is the single classification implementation; this wraps it and
    translates only that sentinel — it does not re-derive classification.
    """

    error: ToolCallError
    result: ToolResult = ""


def classify_tool_exception(
    ex: Exception, function: str
) -> ClassifiedToolException | None:
    """Classify a tool-execution exception as an expected tool failure.

    Thin adapter over tool_call_error() for #3053: translates its `None`
    "no partial result" sentinel to `""`. See ClassifiedToolException.

    Args:
        ex: The (normalized) exception raised by tool execution.
        function: Tool function name (used in messages).

    Returns:
        ClassifiedToolException with the error (and any partial result,
        e.g. truncated output from a sandbox timeout), or None if the
        exception is unexpected.
    """
    mapped = tool_call_error(ex, function)
    if mapped is None:
        return None
    return ClassifiedToolException(
        error=mapped.error, result=mapped.result if mapped.result is not None else ""
    )


ToolResultContent = (
    str
    | list[ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument]
)
"""Content forms a tool result may take after massaging."""


class ResolvedToolContent(NamedTuple):
    """A tool result massaged for recording."""

    content: ToolResultContent
    """The recorded content."""

    truncated: tuple[int, int] | None
    """(raw_bytes, truncated_bytes) when truncation occurred, otherwise `None`."""


def resolve_tool_content(
    result: ToolResult, function: str, max_output: int | None
) -> ResolvedToolContent:
    """Massage a tool result for recording, truncating oversize text.

    Shared by the model tool path and the human agent tool path: valid
    Content values (single or list) pass through structurally untouched;
    everything else is stringified and truncated to the active output cap.

    Args:
        result: Raw ToolResult from tool execution.
        function: Tool function name (used in the truncation marker).
        max_output: Maximum output bytes (None uses the active generate
            config, falling back to the 16 KiB default).

    Returns:
        The recorded content, with (raw_bytes, truncated_bytes) when
        truncation occurred.
    """
    truncated: tuple[int, int] | None = None
    content: ToolResultContent
    result_content = tool_result_content_list(result)
    if result_content is not None:
        content = result_content
    else:
        content = str(result)

        # truncate if necessary
        truncated_output = truncate_tool_output(function, content, max_output)
        if truncated_output:
            content = truncated_output.output
            truncated = (
                truncated_output.raw_bytes,
                truncated_output.truncated_bytes,
            )
    return ResolvedToolContent(content=content, truncated=truncated)


def tool_call_view(call: ToolCall, tdefs: list[ToolDef]) -> ToolCallContent | None:
    tool_def = next((tool for tool in tdefs if tool.name == call.function), None)
    if tool_def and tool_def.viewer:
        try:
            return tool_def.viewer(call).call
        except Exception as ex:
            warn_once(
                logger,
                f"Error in viewer for tool '{call.function}': {ex}. "
                "Falling back to default rendering.",
            )
            return None
    else:
        return None


def validate_tool_input(input: dict[str, Any], parameters: ToolParams) -> str | None:
    from jsonschema import Draft7Validator

    schema = parameters.model_dump(exclude_none=True)
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(input))
    if errors:
        message = "\n".join(
            [f"Found {len(errors)} validation errors parsing tool input arguments:"]
            + [f"- {error.message}" for error in errors]
        )
        return message
    else:
        return None


def tool_result_content_list(
    result: ToolResult,
) -> (
    list[ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument]
    | None
):
    """Content a tool result is passed to the model as, if any.

    Returns `None` for any other result, which is converted to a string and
    truncated to the tool's output limit (`truncate_tool_output()`).
    """
    if isinstance(
        result,
        ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument,
    ):
        return [result]
    elif isinstance(result, list) and all(
        isinstance(
            r,
            ContentText | ContentImage | ContentAudio | ContentVideo | ContentDocument,
        )
        for r in result
    ):
        return result
    else:
        return None


def _tool_max_output(
    tdefs: list[ToolDef], tool_name: str, max_output: int | None
) -> int | None:
    """Resolve the output limit for a tool call.

    A tool that declares its own `max_output` is making a claim about its
    result (e.g. `submit()`, whose result becomes the agent's completion, and
    the deep agent's `agent()`, whose result is a subagent's report), so that
    declaration wins over the caller/generate config value.

    Args:
        tdefs: Tool definitions in scope for this execution.
        tool_name: Name of the called tool (unresolved names fall back to
            `max_output`).
        max_output: Limit passed to `execute_tools()` (None defers to the
            active `GenerateConfig`).
    """
    tdef = next((tdef for tdef in tdefs if tdef.name == tool_name), None)
    if tdef is not None and tdef.max_output is not None:
        return tdef.max_output
    return max_output


class TruncatedToolOutput(NamedTuple):
    output: str
    raw_bytes: int
    truncated_bytes: int


def truncate_tool_output(
    tool_name: str, output: str, max_output: int | None
) -> TruncatedToolOutput | None:
    # determine active max output
    active_max_output = max_output
    if active_max_output is None:
        active_max_output = active_generate_config().max_tool_output
        if active_max_output is None:
            active_max_output = 16 * 1024

    # truncate if required
    truncated = truncate_string_to_bytes(output, active_max_output)
    if truncated:
        truncated_output = dedent("""
            The output of your call to {tool_name} was too long to be displayed.
            Here is a truncated version:
            <START_TOOL_OUTPUT>
            {truncated_output}
            <END_TOOL_OUTPUT>
            """).format(tool_name=tool_name, truncated_output=truncated.output)
        return TruncatedToolOutput(
            truncated_output, truncated.original_bytes, active_max_output
        )
    else:
        return None


def tool_parse_error_message(arguments: str | None, ex: Exception) -> str:
    # middle-truncate the raw arguments (they can be arbitrarily large when the
    # model goes off the rails, and this message is echoed back to the model)
    truncated = truncate_string_to_bytes(arguments or "", 16 * 1024)
    shown = (
        f"{truncated.output}\n\n(arguments middle-truncated from {truncated.original_bytes} bytes)"
        if truncated
        else (arguments or "")
    )
    return f"Error parsing the following tool call arguments:\n\n{shown}\n\nError details: {ex}"


MAX_TOOL_CALL_ARGUMENTS_DEPTH = 100
"""Maximum nesting depth accepted for model-emitted tool call arguments.

Deeper structures are rejected with a tool parsing error (echoed back to
the model) rather than admitted: downstream consumers of arguments only
tolerate bounded nesting (pydantic-core validates and serializes to a hard
depth limit of ~255, and log condensation walks values recursively), so
unbounded depth would crash sample logging rather than the sample itself.

Enforced in `parse_tool_call` for providers that deliver arguments as a
string (recorded as `ToolCall.parse_error`) and again in `call_tool` for
every provider, including those that construct `ToolCall` from an
already-parsed dict and so never reach `parse_tool_call`. Under approval or a
sentinel, `validated_tool_call` also enforces it on the converted arguments
that are shown and logged, since conversion can add nesting.
"""


def _exceeds_max_depth(value: object) -> bool:
    return exceeds_max_depth(value, MAX_TOOL_CALL_ARGUMENTS_DEPTH)


def _max_depth_parse_error() -> ValueError:
    return ValueError(
        f"arguments exceed the maximum supported nesting depth of "
        f"{MAX_TOOL_CALL_ARGUMENTS_DEPTH}"
    )


def _object_with_trailing_quotes(arguments: str) -> dict[str, Any] | None:
    """Recover a complete JSON object trailed only by stray double quotes.

    Models generating a call to a tool whose parameters are empty or all
    optional sometimes emit the empty body plus loose quotes (e.g. `{}""`),
    which fails `json.loads`. The arguments arrive verbatim from the provider,
    so the recovery has to happen here. Only double quotes are treated as
    stray, since that's the artifact actually observed; a single quote in the
    trailing text is left to still surface as a parse error.

    Args:
        arguments: Tool call arguments that failed to parse as JSON.

    Returns:
        The leading object, or None if the trailing text is anything other
        than double quotes and whitespace, so that truncated or doubled
        payloads (e.g. `{"a": 1}{"a": 2}`) still surface as parse errors.
    """
    try:
        value, index = json.JSONDecoder().raw_decode(arguments)
    except (json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    if set(arguments[index:]) - {'"'} - set(string.whitespace):
        return None
    return cast(dict[str, Any], value)


def parse_tool_call(
    id: str,
    function: str,
    arguments: str | None,
    tools: list[ToolInfo] | None = None,
    type: Literal["function", "custom"] = "function",
) -> ToolCall:
    """Parse a tool call from a JSON payload.

    Note that this function doesn't know about internal tool names so the caller
    should ammend the returned `ToolCall` by mapping the parsed `function` field from
    from an internal name to an inspect tool name and fixing up the `ToolCall` object
    as required to reflect this change.
    """
    error: str | None = None
    arguments_dict: dict[str, Any] = {}

    def report_parse_error(ex: Exception) -> None:
        nonlocal error
        error = tool_parse_error_message(arguments, ex)
        logger.info(error)

    # if the arguments is a dict, then handle it with a plain json.loads
    arguments = (arguments or "").strip()
    if arguments.startswith("{"):
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(arguments)
        except RecursionError:
            # nested beyond even what json.loads tolerates
            report_parse_error(_max_depth_parse_error())
        except json.JSONDecodeError as ex:
            parsed = _object_with_trailing_quotes(arguments)
            if parsed is not None:
                truncated = truncate_string_to_bytes(arguments, 256)
                shown = truncated.output if truncated else arguments
                logger.info(
                    f"Recovered arguments for tool call '{function}' from a "
                    f"complete JSON object trailed by stray quote characters: {shown}"
                )
            else:
                report_parse_error(ex)
        if parsed is not None:
            if _exceeds_max_depth(parsed):
                report_parse_error(_max_depth_parse_error())
            else:
                arguments_dict = parsed

    # otherwise parse it as yaml (which will pickup unquoted strings, numbers, and true/false)
    # and then create a dict that maps it to the first function argument
    elif function and tools:
        tool_info = next(
            (
                tool
                for tool in tools
                if tool.name == function and len(tool.parameters.properties) > 0
            ),
            None,
        )
        if tool_info:
            param_names = list(tool_info.parameters.properties.keys())
            value: Any = None
            try:
                value = yaml.safe_load(arguments)
            except yaml.error.YAMLError:
                # If the yaml parser fails, we treat it as a string argument.
                value = arguments
            except RecursionError:
                # nested beyond even what yaml.safe_load tolerates
                report_parse_error(_max_depth_parse_error())
            if error is None:
                if _exceeds_max_depth(value):
                    report_parse_error(_max_depth_parse_error())
                else:
                    arguments_dict[param_names[0]] = value

    # return ToolCall with error payload
    return ToolCall(
        id=id, function=function, arguments=arguments_dict, parse_error=error, type=type
    )


async def call_tools(
    message: ChatMessageAssistant,
    tools: list[Tool] | list[ToolDef] | list[Tool | ToolDef],
    max_output: int | None = None,
) -> list[ChatMessageTool]:
    """Perform tool calls in assistant message.

    This method is deprecated. Use the `execute_tools()` method instead
    (which correctly handles agent `handoff()` tools).

    Args:
       message: Assistant message.
       tools (list[Tool]): Available tools
       max_output (int | None): Maximum output length (in bytes).
          Defaults to max_tool_output from active GenerateConfig
          (16 * 1024 by default).

    Returns:
       Messages added to the conversation.
    """
    warn_once(
        logger,
        "call_tools is deprecated -- please use execute_tools instead (as it supports agent handoff tools)",
    )

    messages, _ = await execute_tools([message], tools, max_output)
    return [m for m in messages if isinstance(m, ChatMessageTool)]
