import fnmatch
import re
from dataclasses import dataclass
from re import Pattern
from typing import Generator

from rich import print
from rich.panel import Panel

from inspect_ai._util.registry import registry_log_name
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall

from ._approver import Approval, Approver
from ._config import approval_policies_from_config


@dataclass
class ApprovalPolicy:
    approver: Approver
    tools: str | list[str]


def policy_approver(
    policies: str | list[ApprovalPolicy], print: bool = True, log: bool = True
) -> Approver:
    # if policies is a str then its a config file
    if isinstance(policies, str):
        policies = approval_policies_from_config(policies)

    # compile policy into approvers and regexes for matching
    policy_matchers: list[tuple[list[Pattern[str]], Approver]] = []
    for policy in policies:
        tools = [policy.tools] if isinstance(policy.tools, str) else policy.tools
        patterns = [re.compile(fnmatch.translate(tool)) for tool in tools]
        policy_matchers.append((patterns, policy.approver))

    # generator for policies that match a tool_call
    def tool_approvers(tool_call: ToolCall) -> Generator[Approver, None, None]:
        for policy_matcher in iter(policy_matchers):
            if any(
                [pattern.match(tool_call.function) for pattern in policy_matcher[0]]
            ):
                yield policy_matcher[1]

    async def approve(
        tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        # process approvers for this tool call (continue loop on "escalate")
        for approver in tool_approvers(tool_call):
            approval = await call_approver(
                approver, tool_call, tool_view, state, print, log
            )
            if approval.decision != "escalate":
                return approval

        # if there are no approvers then we reject
        reject = Approval(
            decision="reject",
            explanation=f"No approvers registered for tool {tool_call.function}",
        )
        # record and return the rejection
        record_approval("policy", reject, tool_call, print, log)
        return reject

    return approve


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
