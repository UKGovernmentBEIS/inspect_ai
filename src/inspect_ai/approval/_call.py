import inspect
from copy import deepcopy
from logging import getLogger

from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import registry_log_name
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from ._approval import Approval
from ._approver import Approver

logger = getLogger(__name__)


async def call_approver(
    approver: Approver,
    message: str,
    call: ToolCall,
    view: ToolCallView,
    history: list[ChatMessage],
) -> Approval:
    # the event records the call as presented, which the approver may change
    presented, presented_view = deepcopy(call), deepcopy(view)

    # run approver (if the approval is still using state then
    # provide that but issue a warning)
    signature = inspect.signature(approver)
    if "state" in signature.parameters.keys():
        from inspect_ai.solver._task_state import sample_state

        warn_once(
            logger, "Approver 'state' parameter is deprecated (use 'history' instead)"
        )
        approval = await approver(message, call, view, sample_state())  # type: ignore[arg-type]
    else:
        approval = await approver(message, call, view, history)

    # record
    record_approval(
        registry_log_name(approver), message, presented, presented_view, approval
    )

    # return approval
    return approval


def record_approval(
    approver_name: str,
    message: str,
    call: ToolCall,
    view: ToolCallView | None,
    approval: Approval,
) -> None:
    """Record an approval decision as an `ApprovalEvent`.

    The event holds copies of the call, view and modified call, since the
    event stores objects by reference and later code can change them.
    """
    from inspect_ai.log._transcript import transcript

    transcript()._event(
        ApprovalEvent(
            message=message,
            call=deepcopy(call),
            view=deepcopy(view),
            approver=approver_name,
            decision=approval.decision,
            modified=deepcopy(approval.modified),
            explanation=approval.explanation,
            metadata=approval.metadata,
        )
    )
