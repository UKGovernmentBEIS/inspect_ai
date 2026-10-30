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

Each call is reviewed as the tool it will run (`AgentBridge.reviewed_calls`), so
policies match that tool's own name and approvers see its own arguments. For a sandbox
bridge that is the bridged tool the call's execution grant will bind, whatever name
the scaffold declared it under, and for a call made through a scaffold's dispatcher
function it is the bridged tool the dispatcher names; a `modify` decision is mapped
back onto the call the scaffold receives.
"""

import sys
from contextlib import AbstractContextManager, nullcontext
from copy import deepcopy
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, Sequence

from inspect_ai._util.format import format_function_call
from inspect_ai._util.logger import warn_once
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallError
from inspect_ai.tool._tool_info import ToolInfo

if TYPE_CHECKING:
    from inspect_ai.approval._policy import ApprovalPolicy

logger = getLogger(__name__)


def bridge_approval_scope(
    approval: list["ApprovalPolicy"] | None,
) -> AbstractContextManager[None]:
    """Activate a bridge's own approval policies, or fall back to ambient ones."""
    from inspect_ai.approval._apply import approval as approval_context

    return approval_context(approval) if approval else nullcontext()


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
    tools: Sequence[ToolInfo | Tool],
) -> BridgeApproval:
    """Approve the tool calls in a bridged model response.

    Calls are approved in order and evaluation stops at the first non-approval, so a
    human isn't asked to decide on calls that are about to be discarded anyway.
    `terminate` doesn't return, and neither does a `modify` decision that changes the
    function called or the call's id: that is an error in the approver, and fails
    the sample. An `approve` from an approver that changed the call it was shown in
    place is a rejection. Both are judged against a snapshot of the call taken
    before review, by the rules native execution uses (`approver_result_error`).

    Each call is reviewed as each tool it would run (`AgentBridge.reviewed_calls`),
    and is approved only if every one of those reviews approves it. A `modify`
    decision for a call that would run several bridged tools (they share a served
    description) also fails the sample: the tools' other reviews approved the
    unmodified arguments, and the grants for all of them would bind the modified
    ones.

    A multi-choice response whose alternate choices carry tool calls is reduced to
    the primary choice (with a warning) when approval is active, since only the
    primary choice is reviewed, and always for a bridge that grants host-tool
    execution (`AgentBridge.grants_tool_execution`), since only the primary
    choice's calls are granted: returning the others would hand the scaffold tool
    calls no approver saw or no grant covers. Text-only alternates pass through,
    as does everything for an in-process bridge without a policy.

    Args:
        bridge: Bridge whose `approval` policies (if any) apply for this call.
        output: Model output about to be handed to the scaffold.
        history: Conversation that produced `output`.
        tools: Declarations the scaffold made to the model in the request that
            produced `output`, which resolve what each call would run.

    Returns:
        The response for the scaffold, plus the messages to replay to the model when
        the response was rejected.
    """
    from inspect_ai.approval._apply import apply_tool_approval, have_tool_approval
    from inspect_ai.approval._approval import Approval
    from inspect_ai.model._call_tools import approver_result_error

    with bridge_approval_scope(bridge.approval):
        approval_active = have_tool_approval()
        if (approval_active or bridge.grants_tool_execution) and any(
            choice.message.tool_calls for choice in output.choices[1:]
        ):
            warn_once(
                logger,
                "Only the primary choice of a bridged response is reviewed and "
                "granted execution; dropping alternate choices that carry tool "
                "calls. Request a single choice (n=1) from a bridged agent.",
            )
            output = output.model_copy(update={"choices": output.choices[:1]})

        if not approval_active:
            return BridgeApproval(output, None)

        tool_calls = output.message.tool_calls
        if not tool_calls:
            return BridgeApproval(output, None)

        # approvers see the assistant turn under review, matching the native path
        # where the conversation ends with the message carrying the tool calls: an
        # approver may weigh a call against its siblings. A new list, so the input
        # the caller hands to `_track_state` is untouched.
        approval_history = history + [output.message]
        message = output.message.text
        modified: dict[str, dict[str, Any]] = {}
        for call in tool_calls:
            reviewed_calls = bridge.reviewed_calls(call, tools)
            for target in reviewed_calls.calls:
                # each review gets its own copy, sharing nothing with the proposal
                # or another review; its decision is judged against `shown`
                reviewed = deepcopy(target)
                shown = deepcopy(target)
                # no viewer: bridged tools reach us as ToolInfo from the scaffold's
                # request, not as ToolDef, so there is no registered viewer to
                # resolve. apply_tool_approval falls back to its default rendering.
                approved, approval = await apply_tool_approval(
                    message, reviewed, None, approval_history
                )
                error = (
                    approver_result_error(shown, reviewed, approval)
                    if approved
                    else None
                )
                if error is not None and approval is not None:
                    if approval.decision == "modify":
                        failure = RuntimeError(error)
                        bridge.request_fail(failure)
                        raise failure
                    # an approve of a call changed in place is a rejection
                    approved, approval = (
                        False,
                        Approval(decision="reject", explanation=error),
                    )
                if not approved:
                    explanation = (approval.explanation if approval else None) or (
                        f"Tool call '{shown.function}' was rejected by the "
                        "approval policy."
                    )
                    if approval is not None and approval.decision == "terminate":
                        bridge.request_terminate(
                            f"Tool call approver requested termination: {explanation}"
                        )
                    return BridgeApproval(
                        output, rejection_messages(output, call, explanation)
                    )

                # as on the native path, only a `modify` decision rewrites the
                # call; a `modified` call attached to an `approve` is ignored
                if (
                    approval is not None
                    and approval.decision == "modify"
                    and approval.modified is not None
                ):
                    if len(reviewed_calls.calls) > 1:
                        failure = RuntimeError(
                            f"An approver modified a call to '{shown.function}' "
                            "that would run several bridged tools sharing a "
                            "description. A modified call can't be approved for "
                            "all of them; give the bridged tools distinct "
                            "descriptions."
                        )
                        bridge.request_fail(failure)
                        raise failure
                    modified[call.id] = reviewed_calls.dispatch(
                        approval.modified.arguments
                    )

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
    (`call_tool()` in `model/_call_tools.py`).

    Only the arguments are adopted: a `modify` decision may not change the function
    (`apply_bridge_tool_approval` fails the sample if it does).
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
