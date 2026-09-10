import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from logging import getLogger

from inspect_ai._util.format import format_function_call
from inspect_ai._util.logger import warn_once
from inspect_ai.approval._approval import Approval, ApprovalStage
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
)
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit

from ._approver import Approver
from ._policy import ApprovalPolicy, approval_policies_from_config, policy_approver

logger = getLogger(__name__)


async def apply_tool_approval(
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> tuple[bool, Approval | None]:
    approver = _tool_approver.get(None)
    if approver:
        approval = await _call_approver(approver, message, call, viewer, history)

        # process decision
        match approval.decision:
            case "approve" | "modify":
                return True, approval
            case "reject":
                return False, approval
            case "terminate":
                return False, approval
            case "escalate":
                raise RuntimeError("Unexpected 'escalate' from policy approver.")

    # no approval system registered
    else:
        return True, None


async def apply_tool_result_approval(
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
    result: ChatMessageTool,
) -> tuple[bool, Approval | None]:
    """Apply result-stage approval policies to an executed tool call.

    The approver sees the same arguments as at the call stage, with `result`
    appended to `history` so that the conversation it reviews ends with the
    tool's output. A 'modify' decision is an error here: the call has already
    executed, so there is nothing left to modify.

    Returns:
        Whether the result may be given to the model, and the approval that
        decided it (`None` when no result-stage policies are registered).
    """
    approver = _tool_result_approver.get(None)
    if approver:
        # a copy, so an approver cannot alter what the model receives in place
        approval = await _call_approver(
            approver, message, call, viewer, [*history, result.model_copy()]
        )

        # process decision
        match approval.decision:
            case "approve":
                return True, approval
            case "reject":
                return False, approval
            case "terminate":
                return False, approval
            case "modify":
                raise RuntimeError(
                    f"Approver returned 'modify' for the result of tool "
                    f"'{call.function}'. A tool result cannot be modified: "
                    "return 'approve', 'reject', 'escalate', or 'terminate' "
                    "from result-stage approvers."
                )
            case "escalate":
                raise RuntimeError("Unexpected 'escalate' from policy approver.")

    # no result approval registered
    else:
        return True, None


def default_tool_call_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(
            format="markdown",
            content="```python\n"
            + format_function_call(call.function, call.arguments)
            + "\n```\n",
        )
    )


@contextlib.contextmanager
def approval(
    policies: str | list[ApprovalPolicy],
) -> Iterator[None]:
    """Context manager to temporarily replace tool approval policies.

    Each stage that `policies` declares is replaced for the duration of the
    context; a stage it does not declare keeps the policies already in effect,
    so a result-stage monitor added for a section does not switch off the
    call-stage approval around it (and vice versa). An empty list keeps its
    long-standing meaning of rejecting every tool call.

    Args:
        policies: Approval policies (or a policy config file) to use within
            the context.
    """
    if isinstance(policies, str):
        policies = approval_policies_from_config(policies)
    call_token = _tool_approver.set(_context_call_approver(policies))
    result_token = _tool_result_approver.set(
        _stage_approver(policies, "result")
        if _declares_stage(policies, "result")
        else _tool_result_approver.get(None)
    )
    try:
        yield
    finally:
        _tool_result_approver.reset(result_token)
        _tool_approver.reset(call_token)


def init_tool_approval(approval: list[ApprovalPolicy] | None) -> None:
    if approval:
        _tool_approver.set(_stage_approver(approval, "call"))
        _tool_result_approver.set(_stage_approver(approval, "result"))
    else:
        _tool_approver.set(None)
        _tool_result_approver.set(None)


def have_tool_approval() -> bool:
    """Whether approval policies for either stage are in effect."""
    return have_tool_call_approval() or have_tool_result_approval()


def have_tool_call_approval() -> bool:
    return _tool_approver.get(None) is not None


def have_tool_result_approval() -> bool:
    return _tool_result_approver.get(None) is not None


def _stage_approver(
    policies: list[ApprovalPolicy], stage: ApprovalStage
) -> Approver | None:
    """Policy approver for `stage`, or `None` when no policy targets it.

    Without this distinction a policy list holding only result-stage policies
    would leave the call stage with an approver that rejects every call for
    having no approver registered (and vice versa).
    """
    if _declares_stage(policies, stage):
        return policy_approver(policies, stage)
    else:
        return None


def _declares_stage(policies: list[ApprovalPolicy], stage: ApprovalStage) -> bool:
    return any(policy.stage == stage for policy in policies)


def _context_call_approver(policies: list[ApprovalPolicy]) -> Approver | None:
    # an empty list has always meant "no approvers registered": reject every call
    if not policies or _declares_stage(policies, "call"):
        return policy_approver(policies, "call")
    else:
        return _tool_approver.get(None)


async def _call_approver(
    approver: Approver,
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> Approval:
    # resolve view
    if viewer:
        try:
            view = viewer(call)
            if not view.call:
                view.call = default_tool_call_viewer(call).call
        except Exception as ex:
            warn_once(
                logger,
                f"Error in viewer for tool '{call.function}': {ex}. "
                "Falling back to default rendering.",
            )
            view = default_tool_call_viewer(call)
    else:
        view = default_tool_call_viewer(call)

    # call approver (approvers which use model inference — e.g. LLM monitors —
    # shouldn't have that inference charged to the agent's own budget)
    with suspend_token_limit(), suspend_turn_limit():
        return await approver(
            message=message,
            call=call,
            view=view,
            history=history,
        )


_tool_approver: ContextVar[Approver | None] = ContextVar("tool_approver", default=None)

_tool_result_approver: ContextVar[Approver | None] = ContextVar(
    "tool_result_approver", default=None
)
