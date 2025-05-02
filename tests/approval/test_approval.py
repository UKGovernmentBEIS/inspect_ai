from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai.approval import ApprovalDecision, ApprovalPolicy, auto_approver
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import ApprovalEvent
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool._tool import tool


# define tool
@tool
def addition():
    async def execute(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        # return as list[Content] to confirm that codepath works
        return [ContentText(text=str(x + y))]

    return execute


def check_approval(
    policy: str | ApprovalPolicy | list[ApprovalPolicy] | None,
    decision: ApprovalDecision,
    approver: str = "auto",
    task_policy: str | ApprovalPolicy | list[ApprovalPolicy] | None = None,
) -> ApprovalEvent:
    if policy is not None:
        if isinstance(policy, str):
            policy = (Path(__file__).parent / policy).as_posix()

        policy = policy if isinstance(policy, list | str) else [policy]

    if task_policy is not None:
        if isinstance(task_policy, str):
            task_policy = (Path(__file__).parent / task_policy).as_posix()

        task_policy = (
            task_policy if isinstance(task_policy, list | str) else [task_policy]
        )

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
        approval=task_policy,
    )

    log = eval(task, model=model, approval=policy)[0]

    approval = find_approval(log)
    assert approval
    assert approval.approver == approver
    assert approval.decision == decision

    return approval


approve_all_policy = ApprovalPolicy(approver=auto_approver(), tools="*")
reject_all_policy = ApprovalPolicy(approver=auto_approver("reject"), tools="*")


def test_approve():
    check_approval(approve_all_policy, decision="approve")


def test_approve_reject():
    check_approval(reject_all_policy, decision="reject")
    check_approval(None, decision="reject", task_policy=reject_all_policy)


def test_approve_pattern():
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools="add*"), decision="approve"
    )
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools="foo*"),
        decision="reject",
        approver="policy",
        task_policy=approve_all_policy,
    )


def test_approve_multi_pattern():
    check_approval(
        ApprovalPolicy(approver=auto_approver(), tools=["spoo*", "add*"]),
        decision="approve",
        task_policy=reject_all_policy,
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
        None,
        decision="approve",
        task_policy=[
            ApprovalPolicy(approver=auto_approver("reject"), tools="foo*"),
            ApprovalPolicy(approver=auto_approver("approve"), tools="add*"),
        ],
    )


def test_approve_config():
    check_approval("approve.yaml", decision="approve")


def test_approve_config_reject():
    check_approval(None, decision="reject", task_policy="reject.yaml")


def test_approve_config_terminate():
    check_approval("terminate.yaml", decision="terminate", task_policy="reject.yaml")


def test_approve_config_escalate():
    check_approval("escalate.yaml", decision="reject", approver="policy")


def find_approval(log: EvalLog) -> ApprovalEvent | None:
    if log.samples:
        return next(
            (
                event
                for event in reversed(log.samples[0].events)
                if isinstance(event, ApprovalEvent)
            ),
            None,
        )
    else:
        return None


if __name__ == "__main__":
    test_approve_escalate()
