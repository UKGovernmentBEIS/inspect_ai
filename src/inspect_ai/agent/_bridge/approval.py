"""Tool approval for bridged agents.

Bridged scaffolds (claude_code, codex, …) execute their own tool calls, so they
never reach `execute_tools()` — the one place Inspect normally applies approval
policies. Without a gate here, `--approval` (and therefore human intervention
and monitor-style approvers) silently has no effect on a bridged eval.

`bridge_generate()` is the single chokepoint where the scaffold's intended tool
calls exist as Inspect `ToolCall`s *before* the scaffold acts on them, so that
is where we gate them.

Rejection semantics
-------------------
The bridge is a model endpoint: it can only shape the assistant reply, and
cannot fabricate the tool results (those belong to the scaffold). So a rejected
call is *removed* from the reply — the scaffold never sees it and therefore
never runs it — and the reason is appended to the reply as text so the model
learns why. Approved siblings are left in place, meaning a partially-rejected
turn continues naturally; a fully-rejected turn becomes a text-only reply,
which most scaffolds treat as end-of-turn.
"""

from typing import Sequence

from inspect_ai._util.content import ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.approval._approval import Approval
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool import Tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallViewer
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo


async def apply_bridge_tool_approval(
    output: ModelOutput,
    history: list[ChatMessage],
    tools: Sequence[ToolInfo | Tool],
) -> None:
    """Apply active approval policies to the tool calls in a bridged reply.

    Modifies `output` in place: `modify` decisions replace the call the scaffold
    will run, rejected calls are dropped and explained in the reply text, and
    `terminate` raises `TerminateSampleError`.

    Args:
        output: Model output whose tool calls the scaffold is about to run.
        history: Conversation the output was generated from (approver context).
        tools: Tools available for this generation, used to resolve tool call
            viewers. Scaffold-native tools arrive as `ToolInfo` and so have no
            viewer — those fall back to the default rendering.
    """
    from inspect_ai.approval._apply import apply_tool_approval, have_tool_approval

    message = output.message
    if not have_tool_approval() or not message.tool_calls:
        return

    viewers = _tool_call_viewers(tools)
    approved: list[ToolCall] = []
    rejections: list[str] = []
    for call in message.tool_calls:
        ok, approval = await apply_tool_approval(
            message.text, call, viewers.get(call.function), history
        )
        if ok:
            approved.append(
                approval.modified if approval and approval.modified else call
            )
        elif approval and approval.decision == "terminate":
            raise TerminateSampleError("Tool call approver requested termination.")
        else:
            rejections.append(_rejection_message(call, approval))

    # write back the surviving calls (picking up any `modify` substitutions)
    message.tool_calls = approved
    if not rejections:
        return

    if isinstance(message.content, str):
        message.content = "\n\n".join([message.content, *rejections]).lstrip()
    else:
        message.content = message.content + [
            ContentText(text=text) for text in rejections
        ]

    # a reply with no remaining tool calls is a plain assistant turn
    if not approved:
        output.choices[0].stop_reason = "stop"


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


def _rejection_message(call: ToolCall, approval: Approval | None) -> str:
    explanation = (approval.explanation if approval else None) or "Not approved."
    return f"The call to the `{call.function}` tool was rejected: {explanation}"
