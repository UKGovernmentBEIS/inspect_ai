"""Tool approval for bridged agents.

Bridged scaffolds (claude_code, codex, …) execute their own tool calls, so they
never reach `execute_tools()` — the one place Inspect normally applies approval
policies. Without a gate here, `--approval` (and therefore human intervention
and monitor-style approvers) silently has no effect on a bridged eval.

`bridge_generate()` is the single chokepoint where the scaffold's intended tool
calls exist as Inspect `ToolCall`s *before* the scaffold acts on them, so that
is where approval is applied.
"""

from typing import Sequence

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.approval._approval import Approval
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallError, ToolCallViewer
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo


async def resolve_bridge_tool_approvals(
    output: ModelOutput,
    history: list[ChatMessage],
    tools: Sequence[ToolInfo | Tool],
) -> tuple[ModelOutput, list[ChatMessage] | None]:
    """Apply active approval policies to a bridged reply's tool calls.

    Returns `(output, None)` when the turn can proceed as-is: no tool call
    was rejected. `modify` substitutions are applied to a *copy* of `output`,
    so the transcript's `ModelEvent` (which shares the original object) still
    shows exactly what the model asked for — matching how a native `modify`
    leaves the recorded `ToolEvent` showing the original call, with the
    substitution visible separately via the `ApprovalEvent`.

    Returns `(output, continuation)` when any call was rejected. The bridge
    can only shape the reply, not fabricate a scaffold-executed result, so
    there's no way to hand the scaffold a rejected call it could ever resolve
    — the whole turn is discarded instead. `continuation` is the rejected
    assistant message plus one tool-result message per call (the real
    decision for whichever call(s) were rejected; a "turn discarded" note for
    any approved siblings), for the caller to append to the conversation and
    regenerate — the same shape a native rejection becomes (a tool result the
    model sees on its next turn), just kept internal to the retry loop since
    it can never reach the scaffold. Bounded only by the sample's own limits
    (message/token/time/cost), the same as an ordinary agentic loop that keeps
    retrying a rejected tool call.

    `terminate` raises `TerminateSampleError` directly, ending the sample.
    """
    from inspect_ai.approval._apply import apply_tool_approval, have_tool_approval

    message = output.message
    if not have_tool_approval() or not message.tool_calls:
        return output, None

    viewers = _tool_call_viewers(tools)
    decisions: list[tuple[ToolCall, bool, Approval | None]] = []
    for call in message.tool_calls:
        approved, approval = await apply_tool_approval(
            message.text, call, viewers.get(call.function), history
        )
        if approval and approval.decision == "terminate":
            raise TerminateSampleError("Tool call approver requested termination.")
        decisions.append((call, approved, approval))

    if all(approved for _, approved, _ in decisions):
        if any(approval and approval.modified for _, _, approval in decisions):
            output = output.model_copy(deep=True)
            output.message.tool_calls = [
                approval.modified if approval and approval.modified else call
                for call, _, approval in decisions
            ]
        return output, None

    results = [
        _rejection_result(call, approved, approval)
        for call, approved, approval in decisions
    ]
    return output, [message, *results]


def _rejection_result(
    call: ToolCall, approved: bool, approval: Approval | None
) -> ChatMessageTool:
    if approved:
        explanation = "Not executed: a sibling tool call in this turn was rejected."
    else:
        explanation = (approval.explanation if approval else None) or "Not approved."
    return ChatMessageTool(
        tool_call_id=call.id,
        function=call.function,
        content="",
        error=ToolCallError("approval", explanation),
    )


def _tool_call_viewers(
    tools: Sequence[ToolInfo | Tool],
) -> dict[str, ToolCallViewer]:
    """Viewers by tool name for the tools that have one."""
    viewers: dict[str, ToolCallViewer] = {}
    for tool in tools:
        if isinstance(tool, ToolInfo):
            continue
        tool_def = ToolDef(tool)
        if tool_def.viewer is not None:
            viewers[tool_def.name] = tool_def.viewer
    return viewers
