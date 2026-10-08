import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

from inspect_ai.approval._approval import Approval
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallViewer,
    resolve_tool_call_view,
)
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit

from ._approver import Approver
from ._policy import ApprovalPolicy, policy_approver

MODIFY_WITHOUT_CALL = (
    "The approver chose to modify this tool call but supplied no modified call, "
    "so the call was not run."
)


async def apply_tool_approval(
    message: str,
    call: ToolCall,
    viewer: ToolCallViewer | None,
    history: list[ChatMessage],
) -> tuple[bool, Approval | None]:
    approver = _tool_approver.get(None)
    if approver:
        view = resolve_tool_call_view(call, viewer)

        # call approver (approvers which use model inference — e.g. LLM monitors —
        # shouldn't have that inference charged to the agent's own budget)
        with suspend_token_limit(), suspend_turn_limit():
            approval = await approver(
                message=message,
                call=call,
                view=view,
                history=history,
            )

        # process decision
        match approval.decision:
            case "approve":
                return True, approval
            case "modify":
                # without a modified call there is nothing approved to run, and
                # running the original would contradict the recorded decision
                if approval.modified is None:
                    return False, Approval(
                        decision="reject", explanation=MODIFY_WITHOUT_CALL
                    )
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


def modified_function_error(call: ToolCall, modified: ToolCall) -> str | None:
    """Error for a `modify` decision that changes the function called, else `None`.

    A `modify` decision may change only the call's arguments. A different function
    is an error in the eval's approver, not something to report to the model, so
    callers fail the sample with it and run neither tool.
    """
    if modified.function == call.function:
        return None
    return (
        f"An approver returned a modified call to '{modified.function}' for a call "
        f"to '{call.function}'. A 'modify' decision may change only the arguments "
        "of a tool call, not the function called."
    )


@contextlib.contextmanager
def approval(
    policies: list[ApprovalPolicy],
) -> Iterator[None]:
    """Context manager to temporarily replace tool approval policies.

    Args:
        policies: Approval policies to use within the context.
    """
    token = _tool_approver.set(policy_approver(policies))
    try:
        yield
    finally:
        _tool_approver.reset(token)


def init_tool_approval(approval: list[ApprovalPolicy] | None) -> None:
    if approval:
        _tool_approver.set(policy_approver(approval))
    else:
        _tool_approver.set(None)


def have_tool_approval() -> bool:
    return _tool_approver.get(None) is not None


_tool_approver: ContextVar[Approver | None] = ContextVar("tool_approver", default=None)
