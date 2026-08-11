"""Tool approval for bridged agents.

A bridged scaffold runs its own tool loop, so Inspect never executes its tool calls
and the `execute_tools()` approval path never runs. This module applies the approval
chain to the tool calls in a bridged model response instead, at the
`bridge_generate` chokepoint every bridge configuration shares.

A rejection is resolved as an internal round-trip rather than by editing the response
the scaffold sees. Inspect can't stop a scaffold from running a tool it has been
handed, and stripping the call reads as "turn complete" to most scaffolds, which
stalls the agent. So the rejected call and a synthetic tool result are appended to
the *model's* input and generation is retried: the model learns it was denied and
proposes something else, while the scaffold sees one ordinary response and its own
conversation never contains the rejected call. This mirrors the native path
(reject -> tool message -> next generate), relocated from `react()` into the bridge.
"""

import sys
from contextlib import nullcontext
from typing import Any, NamedTuple, NoReturn

from inspect_ai._util.format import format_function_call
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_call import ToolCall, ToolCallError

MAX_CONSECUTIVE_REJECTIONS = 3
"""Consecutive rejected generations before the sample is terminated.

A model that keeps proposing rejected calls would otherwise loop forever. Counted
within a single `bridge_generate` call, so a rejection followed by an approved
generation doesn't accumulate.
"""


MAX_CALL_DESCRIPTION = 200
"""Cap on the rendered call used to point at a rejected peer.

Arguments can be arbitrarily large (a file write carries its whole content) and this
description is repeated in every peer's result on every retry, so it is bounded. The
replayed assistant turn already carries the call in full — this only has to identify
which one.
"""


def describe_call(call: ToolCall) -> str:
    """Single-line, length-bounded rendering of a tool call."""
    description = format_function_call(call.function, call.arguments, width=sys.maxsize)
    if len(description) > MAX_CALL_DESCRIPTION:
        description = description[:MAX_CALL_DESCRIPTION].rstrip() + "..."
    return description


class BridgeApproval(NamedTuple):
    """Outcome of approving the tool calls in a bridged model response."""

    output: ModelOutput
    """Response to hand to the scaffold (a copy when a `modify` decision applied)."""

    rejection: list[ChatMessage] | None
    """When set, the response was rejected: replay these and generate again."""


async def apply_bridge_tool_approval(
    bridge: AgentBridge,
    output: ModelOutput,
    history: list[ChatMessage],
) -> BridgeApproval:
    """Approve the tool calls in a bridged model response.

    Calls are approved in order and evaluation stops at the first non-approval, so a
    human isn't asked to decide on calls that are about to be discarded anyway.
    `terminate` doesn't return.

    Args:
        bridge: Bridge whose `approval` policies (if any) apply for this call.
        output: Model output about to be handed to the scaffold.
        history: Conversation that produced `output`.

    Returns:
        The response for the scaffold, plus the messages to replay to the model when
        the response was rejected.
    """
    from inspect_ai.approval._apply import apply_tool_approval, have_tool_approval
    from inspect_ai.approval._apply import approval as approval_context

    tool_calls = output.message.tool_calls
    if not tool_calls:
        return BridgeApproval(output, None)

    cm = approval_context(bridge.approval) if bridge.approval else nullcontext()
    with cm:
        if not have_tool_approval():
            return BridgeApproval(output, None)

        # approvers see the assistant turn under review, matching the native path
        # where the conversation ends with the message carrying the tool calls: an
        # approver may weigh a call against its siblings. A new list, so the input
        # the caller hands to `_track_state` is untouched.
        approval_history = history + [output.message]
        message = output.message.text
        modified: dict[str, dict[str, Any]] = {}
        for call in tool_calls:
            # no viewer: bridged tools reach us as ToolInfo from the scaffold's
            # request, not as ToolDef, so there is no registered viewer to resolve.
            # apply_tool_approval falls back to its default rendering.
            approved, approval = await apply_tool_approval(
                message, call, None, approval_history
            )
            if not approved:
                explanation = (approval.explanation if approval else None) or (
                    f"Tool call '{call.function}' was rejected by the approval policy."
                )
                if approval is not None and approval.decision == "terminate":
                    bridge.request_terminate(
                        f"Tool call approver requested termination: {explanation}"
                    )
                return BridgeApproval(
                    output, rejection_messages(output, call, explanation)
                )

            if approval is not None and approval.modified is not None:
                modified[call.id] = approval.modified.arguments

    # modifications are adopted only now that the whole response is approved: a later
    # rejection discards every call, and rewriting an earlier one as we went would
    # leave the turn we replay to the model claiming arguments it never produced.
    if modified:
        return BridgeApproval(with_modified_arguments(output, modified), None)

    return BridgeApproval(output, None)


def with_modified_arguments(
    output: ModelOutput, modified: dict[str, dict[str, Any]]
) -> ModelOutput:
    """Copy of `output` with approved argument rewrites applied, keyed by call id.

    A copy, because `output` is the object the `ModelEvent` already recorded and its
    tool calls are the ones each `ApprovalEvent` holds — pydantic stores both by
    reference. Rewriting in place would make the log show the approved arguments as
    the model's original proposal, erasing the evidence that approval changed them.
    The native path avoids this the same way, by rebinding rather than mutating
    (`model/_call_tools.py:653`).

    Only the arguments are adopted. The native path swaps the whole call, but here
    the scaffold dispatches on the function name and may have no handler for a
    substituted one.
    """
    result = output.model_copy(deep=True)
    for call in result.message.tool_calls or []:
        if call.id in modified:
            call.arguments = modified[call.id]
    return result


def rejection_messages(
    output: ModelOutput, rejected: ToolCall, explanation: str
) -> list[ChatMessage]:
    """Build the retry input for a rejected response: assistant message + results.

    Every call in the response gets a result, not just the rejected one. Anthropic
    requires each `tool_use` to be matched by a `tool_result`, and the padding in the
    Anthropic provider only covers the `count_tokens` path, so an unmatched block
    would fail the retry outright.

    The collateral results name the call that caused the rejection. Without that, a
    model whose innocent `read_file` came back rejected may conclude that reading
    files is disallowed and stop attempting it — the opposite of what the policy
    intended.
    """
    tool_calls = output.message.tool_calls or []
    others = len(tool_calls) - 1
    description = describe_call(rejected)

    messages: list[ChatMessage] = [output.message]
    for call in tool_calls:
        if call.id == rejected.id:
            text = explanation
            if others == 1:
                text += " The other tool call in this response was not executed as a result."
            elif others > 1:
                text += (
                    f" The other {others} tool calls in this response were not "
                    "executed as a result."
                )
        else:
            text = (
                "This tool call was not executed because a parallel tool call in the "
                f"same response was rejected: {description} — {explanation} This call "
                "was not itself rejected; you may re-issue it without the rejected "
                "call."
            )
        messages.append(
            ChatMessageTool(
                content="",
                tool_call_id=call.id,
                function=call.function,
                error=ToolCallError("approval", text),
            )
        )
    return messages


def terminate_for_repeated_rejections(bridge: AgentBridge, rejections: int) -> NoReturn:
    """Terminate the sample after too many consecutive rejected generations."""
    bridge.request_terminate(
        f"Tool call approver rejected {rejections} consecutive generations "
        "from the bridged agent."
    )
