from rich import print
from rich.panel import Panel

from inspect_ai._util.registry import registry_log_name
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approval import Approval
from ._approver import Approver


async def call_approver(
    approver: Approver,
    tool_call: ToolCall,
    tool_view: str,
    state: TaskState | None,
    print: bool = True,
    log: bool = True,
) -> Approval:
    # run approver
    approval = await approver(tool_call, tool_view, state)

    # record as required
    record_approval(
        approver_name=registry_log_name(approver),
        approval=approval,
        tool_call=tool_call,
        print=print,
        log=log,
    )

    # return approval
    return approval


def record_approval(
    approver_name: str,
    approval: Approval,
    tool_call: ToolCall,
    print: bool = True,
    log: bool = True,
) -> None:
    # print if requested
    if print:
        match approval.decision:
            case "approve":
                print_approve_message(
                    approver_name=approver_name,
                    tool_call=tool_call,
                    explanation=approval.explanation,
                )
            case "reject":
                print_reject_message(
                    approver_name=approver_name,
                    tool_call=tool_call,
                    explanation=approval.explanation,
                )
            case "terminate":
                print_terminate_message(
                    approver_name=approver_name,
                    tool_call=tool_call,
                    explanation=approval.explanation,
                )
            case "escalate":
                print_escalate_message(
                    approver_name=approver_name,
                    tool_call=tool_call,
                    explanation=approval.explanation,
                )

    # log if requested
    if log:
        from inspect_ai.log._transcript import ApprovalEvent, transcript

        transcript()._event(
            ApprovalEvent(
                tool_call=tool_call,
                approver=approver_name,
                decision=approval.decision,
                explanation=approval.explanation,
            )
        )


def print_approve_message(
    approver_name: str, tool_call: ToolCall, explanation: str | None
) -> None:
    print_tool_message(
        approver_name=approver_name,
        title="Tool Execution",
        subtitle="Approved",
        message="Tool call approved",
        tool_call=tool_call,
        explanation=explanation,
    )


def print_reject_message(
    approver_name: str, tool_call: ToolCall, explanation: str | None
) -> None:
    print_tool_message(
        approver_name=approver_name,
        title="Tool Execution",
        subtitle="Rejected",
        message="Tool call rejected",
        tool_call=tool_call,
        explanation=explanation,
    )


def print_terminate_message(
    approver_name: str, tool_call: ToolCall, explanation: str | None
) -> None:
    print_tool_message(
        approver_name=approver_name,
        title="Execution Terminated",
        subtitle="System Shutdown",
        message="Execution terminated",
        tool_call=tool_call,
        explanation=explanation,
    )


def print_escalate_message(
    approver_name: str, tool_call: ToolCall, explanation: str | None
) -> None:
    print_tool_message(
        approver_name=approver_name,
        title="Tool Execution",
        subtitle="Escalated",
        message="Tool call escalated",
        tool_call=tool_call,
        explanation=explanation,
    )


def print_tool_message(
    approver_name: str,
    title: str,
    subtitle: str,
    message: str,
    tool_call: ToolCall,
    explanation: str | None,
) -> None:
    print(
        Panel(
            f"{message} ({approver_name}):\nFunction: {tool_call.function}\nArguments: {tool_call.arguments}\nReason: {explanation}",
            title=title,
            subtitle=subtitle,
        )
    )
