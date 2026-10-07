from logging import getLogger
from typing import Any, Literal, Sequence, cast

import anyio
from pydantic import JsonValue, TypeAdapter
from shortuuid import uuid

from inspect_ai._util.content import Content, ContentImage, ContentText
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_data_uri
from inspect_ai._util.working import sample_waiting_time
from inspect_ai.agent._channel.observer import null_execution_observer
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._samples import sample_active
from inspect_ai.log._transcript import transcript
from inspect_ai.model._call_tools import (
    _exceeds_max_depth,
    _max_depth_parse_error,
    tool_call_error,
    tool_result_content_list,
    truncate_tool_output,
    validate_tool_input,
)
from inspect_ai.tool._tool import Tool, ToolError, ToolParsingError, ToolResult
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallError
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._span import parent_span, span

from .types import SandboxAgentBridge, _ToolExecutionGrant

logger = getLogger(__name__)

JSON_VALUE_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

OPERATOR_CANCEL_MESSAGE = "Command timed out before completing."


async def execute_host_tool(
    bridge: SandboxAgentBridge, server: str, tool: str, arguments: JsonValue
) -> JsonValue:
    """Execute a bridged tool for the scaffold, record it, and return the result.

    A tool runs only for a call the model proposed in a bridged generation, once
    per proposal (see `SandboxAgentBridge.register_tool_execution_grants`), unless
    its server was registered with `require_proposal=False`.

    Arguments nested deeper than a native call accepts are rejected, and the
    rest are validated against the tool's schema as for a native call, so a
    scaffold's malformed arguments surface as a `ToolParsingError` the model
    can recover from; they are otherwise forwarded as the scaffold sent them.
    Exceptions are classified after unwrapping any task-group
    `ExceptionGroup`, as `execute_tools` does, and with the same
    `tool_call_error` mapping. Those a native call would show the model
    propagate unchanged as the RPC error the scaffold reads as tool output. Any
    other exception is a bug in the eval's tool, which natively fails the
    sample: the unwrapped exception is signalled through `bridge.request_fail`
    so the bridge's monitor task ends the sample at once, and the original
    still propagates so the RPC unwinds with an error reply (the teardown may
    pre-empt its delivery; the scaffold's turn is over either way).

    A result a native call would pass to the model as text (anything but
    content) is truncated to the same output limit, in the same format
    (`truncate_tool_output`).

    Every request is recorded as one `ToolEvent` in a `tool` span, as a native
    call is, with `metadata["bridge"]` describing it (see `ToolEvent`). An
    execution that consumed a grant takes the proposing call's id and is
    recorded in the span of the proposing `ModelEvent`; a denied or rejected
    request gets a fresh id and the error the scaffold receives. A running
    call can be cancelled by the operator like a native one.
    """
    recorded_arguments = (
        arguments
        if isinstance(arguments, dict) and not _exceeds_max_depth(arguments)
        else {}
    )
    metadata = _BridgeMetadata(server, tool)

    if server not in bridge.bridged_tools:
        message = f"Unknown bridged tools server: {server}"
        await _record_rejection(
            tool, recorded_arguments, ToolCallError("parsing", message), metadata
        )
        raise ValueError(message)

    server_tools = bridge.bridged_tools[server]
    if tool not in server_tools:
        message = f"Unknown tool '{tool}' in server '{server}'"
        await _record_rejection(
            tool, recorded_arguments, ToolCallError("parsing", message), metadata
        )
        raise ValueError(message)

    if _exceeds_max_depth(arguments):
        message = f"Error parsing tool call arguments: {_max_depth_parse_error()}"
        await _record_rejection(tool, {}, ToolCallError("parsing", message), metadata)
        raise ToolParsingError(message)

    grant = (
        bridge.consume_tool_execution_grant(server, tool, arguments)
        if isinstance(arguments, dict)
        else None
    )
    if grant is None and server not in bridge.proposal_exempt_servers:
        warn_once(
            logger,
            f"Denied host tool call '{server}/{tool}': the model did not "
            "propose it in a bridged generation (or its proposal has "
            "already executed).",
        )
        message = (
            f"Host tool call '{server}/{tool}' was not proposed by the model "
            "in a bridged generation (a bridged host tool runs once per "
            "proposed call)"
        )
        metadata.grant = "denied"
        await _record_rejection(
            tool, recorded_arguments, ToolCallError("permission", message), metadata
        )
        raise PermissionError(message)

    with parent_span(grant.proposal.span_id if grant is not None else None):
        return await _execute_granted(
            bridge, tool, server_tools[tool], arguments, grant, metadata
        )


class _BridgeMetadata:
    """What `ToolEvent.metadata["bridge"]` records about a host tool request."""

    def __init__(self, server: str, tool: str) -> None:
        self.server = server
        self.tool = tool
        self.function: str | None = None
        self.proposal_id: str | None = None
        self.grant: Literal["consumed", "denied", "exempt"] | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "bridge": {
                "server": self.server,
                "tool": self.tool,
                "function": self.function,
                "proposal_id": self.proposal_id,
                "grant": self.grant,
            }
        }


async def _record_rejection(
    tool: str,
    arguments: dict[str, JsonValue],
    error: ToolCallError,
    metadata: _BridgeMetadata,
    *,
    event_id: str | None = None,
    view: ToolCallContent | None = None,
) -> None:
    """Record a request that did not execute as a completed event in its own `tool` span."""
    event = ToolEvent(
        id=event_id or uuid(),
        function=tool,
        arguments=arguments,
        view=view,
        metadata=metadata.as_metadata(),
    )
    event._set_result(
        result="",
        truncated=None,
        error=error,
        waiting_time=0.0,
        agent=None,
        failed=None,
        message_id=None,
    )
    recorded = False
    try:
        async with span(name=tool, type="tool"):
            transcript()._event(event)
            recorded = True
    except anyio.get_cancelled_exc_class():
        # cancelled while a span-ID provider allocated the span: the request
        # was still received and decided, so it is still recorded
        if not recorded:
            transcript()._event(event)
        raise


async def _execute_granted(
    bridge: SandboxAgentBridge,
    tool: str,
    tool_fn: Tool,
    arguments: JsonValue,
    grant: _ToolExecutionGrant | None,
    metadata: _BridgeMetadata,
) -> JsonValue:
    if grant is not None:
        metadata.function = grant.proposal.call.function
        metadata.proposal_id = grant.proposal.call.id
        metadata.grant = "consumed"
    else:
        metadata.grant = "exempt"
    event_id = grant.proposal.take_id() if grant is not None else uuid()
    view = grant.proposal.call.view if grant is not None else None

    tool_def = ToolDef(tool_fn)
    # jsonschema reports a non-object as a validation error like any other
    validation_errors = validate_tool_input(
        cast(dict[str, Any], arguments), tool_def.parameters
    )
    if validation_errors:
        await _record_rejection(
            tool,
            arguments if isinstance(arguments, dict) else {},
            ToolCallError("parsing", validation_errors),
            metadata,
            event_id=event_id,
            view=view,
        )
        raise ToolParsingError(validation_errors)
    call_arguments = cast(dict[str, JsonValue], arguments)

    event = ToolEvent(
        id=event_id,
        function=tool,
        arguments=call_arguments,
        view=view,
        pending=True,
        metadata=metadata.as_metadata(),
    )
    sample = sample_active()
    observer = (
        sample.execution_observer if sample is not None else null_execution_observer()
    )
    waiting_start = sample_waiting_time()
    recorded = False

    def finalise(
        result: ToolResult = "",
        truncated: tuple[int, int] | None = None,
        error: ToolCallError | None = None,
        failed: bool | None = None,
    ) -> None:
        event._set_result(
            result=result,
            truncated=truncated,
            error=error,
            waiting_time=sample_waiting_time() - waiting_start,
            agent=None,
            failed=failed,
            message_id=None,
            agent_span_id=getattr(tool_fn, "agent_span_id", None),
        )
        if recorded:
            transcript()._event_updated(event)
        else:
            transcript()._event(event)

    cancelled = ToolCallError(
        "cancelled", "Host tool call was cancelled before completing."
    )
    try:
        async with span(name=tool, type="tool"):
            transcript()._event(event)
            recorded = True
            with observer.track_tool_call(event.id, event):
                try:
                    with anyio.CancelScope() as scope:
                        event._set_cancel_fn(scope.cancel)
                        result: ToolResult = await tool_fn(**call_arguments)
                except anyio.get_cancelled_exc_class():
                    # an outer cancellation (bridge teardown, sample limit): the
                    # operator's per-call cancel is absorbed by `scope` instead
                    finalise(error=cancelled)
                    raise
                except Exception as ex:
                    # classify the unwrapped exception, but let the original
                    # propagate: the service dispatcher special-cases a bare
                    # LimitExceededError (ending the sample), and unwrapping a
                    # grouped one would newly route it there
                    inner_ex = inner_exception(ex)
                    mapped = tool_call_error(inner_ex, tool)
                    if mapped is None:
                        finalise(failed=True)
                        bridge.request_fail(inner_ex)
                    else:
                        output, truncated = (
                            _recorded_result(tool, mapped.result, tool_def.max_output)
                            if mapped.result is not None
                            else ("", None)
                        )
                        finalise(result=output, truncated=truncated, error=mapped.error)
                    raise
    except anyio.get_cancelled_exc_class():
        # cancelled while a span-ID provider allocated the span, before the
        # pending event was recorded (a consumed grant is not restored)
        if not recorded:
            finalise(error=cancelled)
        raise

    if scope.cancelled_caught:
        finalise(error=ToolCallError("timeout", OPERATOR_CANCEL_MESSAGE))
        raise ToolError(OPERATOR_CANCEL_MESSAGE)

    output, truncated = _recorded_result(tool, result, tool_def.max_output)
    finalise(result=output, truncated=truncated)

    # Plain strings are returned verbatim (the MCP `tools/call` text part
    # carries them as-is). For anything else, use pydantic_core.to_json so
    # Pydantic models (e.g. list[ContentText] from real MCP tools) are
    # serialized correctly — json.dumps can't handle BaseModel.
    if isinstance(output, str):
        return output
    if isinstance(result, ContentImage) or (
        isinstance(result, list)
        and all(isinstance(content, (ContentText, ContentImage)) for content in result)
        and any(isinstance(content, ContentImage) for content in result)
    ):
        return _mcp_tool_result_content(result)
    return to_json_str_safe(result)


def _recorded_result(
    tool: str, result: ToolResult, max_output: int | None
) -> tuple[ToolResult, tuple[int, int] | None]:
    """The result as the scaffold receives it, and the truncation applied (if any).

    Content is passed through; anything else becomes text truncated to the
    output limit, as for a native call.
    """
    content = tool_result_content_list(result)
    if content is not None:
        return content, None
    text = result if isinstance(result, str) else to_json_str_safe(result)
    truncated = truncate_tool_output(tool, text, max_output)
    if truncated is None:
        return text, None
    return truncated.output, (truncated.raw_bytes, truncated.truncated_bytes)


def _mcp_tool_content_block(content: JsonValue) -> JsonValue:
    match content:
        case {"type": "image", "image": str() as image} if is_data_uri(image):
            return {
                "type": "image",
                "data": data_uri_to_base64(image),
                "mimeType": data_uri_mime_type(image) or "image/png",
            }
        case {"type": "image", "image": str() as image}:
            return {"type": "text", "text": image}
        case _:
            return content


def _mcp_tool_result_content(
    result: ContentImage | Sequence[Content],
) -> list[JsonValue]:
    content = JSON_VALUE_ADAPTER.validate_json(to_json_str_safe(result))
    match content:
        case list():
            return [_mcp_tool_content_block(block) for block in content]
        case _:
            return [_mcp_tool_content_block(content)]
