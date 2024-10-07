from pathlib import Path

from test_helpers.tools import addition
from test_helpers.utils import ensure_test_package_installed

from inspect_ai import Task, eval
from inspect_ai.approval import ApprovalDecision, ApprovalPolicy, auto_approver
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import ApprovalEvent, ToolEvent
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools


def check_approval(
    policy: str | ApprovalPolicy | list[ApprovalPolicy],
    decision: ApprovalDecision,
    approver: str = "auto",
) -> ApprovalEvent:
    if isinstance(policy, str):
        policy = (Path(__file__).parent / policy).as_posix()

    policy = policy if isinstance(policy, list | str) else [policy]

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="addition",
                tool_arguments={"x": 1, "y": 1},
            ),
            ModelOutput.from_content("mockllm/model", content="2"),
        ],
    )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        scorer=match(numeric=True),
    )

    log = eval(task, model=model, approval=policy)[0]

    approval = find_approval(log)
    assert approval
    assert approval.approver == approver
    assert approval.decision == decision

    return approval


def test_approve():
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools="*"), decision="approve"
    )


def test_approve_reject():
    check_approval(
        ApprovalPolicy(approver=auto_approver("reject"), tools="*"), decision="reject"
    )


def test_approve_pattern():
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools="add*"), decision="approve"
    )
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools="foo*"),
        decision="reject",
        approver="policy",
    )


def test_approve_multi_pattern():
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools=["spoo*", "add*"]),
        decision="approve",
    )


def test_approve_escalate():
    check_approval(
        [
            ApprovalPolicy(approver=auto_approver("escalate"), tools="add*"),
            ApprovalPolicy(approver=auto_approver("approve"), tools="add*"),
        ],
        decision="approve",
    )


def test_approve_no_reject():
    check_approval(
        [
            ApprovalPolicy(approver=auto_approver("reject"), tools="foo*"),
            ApprovalPolicy(approver=auto_approver("approve"), tools="add*"),
        ],
        decision="approve",
    )


def test_approve_modify():
    # also tests loading an approver from a package
    ensure_test_package_installed()

    event = check_approval(
        "modify.yaml",
        decision="modify",
        approver="inspect_package/renamer",
    )
    assert event.modified
    assert event.modified.function == "newname"


def test_approve_config():
    check_approval("approve.yaml", decision="approve")


def test_approve_config_reject():
    check_approval("reject.yaml", decision="reject")


def test_approve_config_terminate():
    check_approval("terminate.yaml", decision="terminate")


def test_approve_config_escalate():
    check_approval("escalate.yaml", decision="reject", approver="policy")


def find_approval(log: EvalLog) -> ApprovalEvent | None:
    if log.samples:
        tool_event: ToolEvent | None = next(
            (
                event
                for event in log.samples[0].transcript.events
                if isinstance(event, ToolEvent)
            ),
            None,
        )
        if tool_event:
            return next(
                (
                    ev
                    for ev in reversed(tool_event.events)
                    if isinstance(ev, ApprovalEvent)
                ),
                None,
            )

    return None
