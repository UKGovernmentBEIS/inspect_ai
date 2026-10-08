import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from logging import getLogger

from inspect_ai._util.format import format_function_call
from inspect_ai._util.logger import warn_once
from inspect_ai.approval._approval import Approval
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
)
from inspect_ai.util._limit import suspend_token_limit, suspend_turn_limit

from ._approver import Approver
from ._call import record_approval
from ._policy import ApprovalPolicy, policy_approver

logger = getLogger(__name__)

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
    """Apply the active approval policy to a tool call.

    If the tool's viewer raises, the call is rejected without consulting the
    approvers: an approver deciding on a fallback rendering might approve an
    action that the tool's own view would have shown differently.
    """
    approver = _tool_approver.get(None)
    if approver:
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
                    "Rejecting the tool call.",
                )
                rejection = Approval(
                    decision="reject",
                    explanation=(
                        f"The tool call was rejected because the viewer for tool "
                        f"'{call.function}' failed, so it could not be shown for "
                        f"approval: {ex}"
                    ),
                )
                record_approval("policy", message, call, None, rejection)
                return False, rejection
        else:
            view = default_tool_call_viewer(call)

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
