"""Approval policies grouped into chains: every covering chain runs, strictest wins."""

from pathlib import Path

import anyio

from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._policy import (
    ApprovalPolicyConfig,
    ApproverPolicyConfig,
    approval_policies_from_config,
    config_from_approval_policies,
    policy_approver,
)
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import ChatMessage
from inspect_ai.tool._tool_call import ToolCall, ToolCallView


@approver(name="fixed")
def fixed_approver(decision: ApprovalDecision = "approve") -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        modified = (
            ToolCall(id=call.id, function=call.function, arguments={"cmd": "echo"})
            if decision == "modify"
            else None
        )
        return Approval(
            decision=decision, modified=modified, explanation=f"fixed {decision}"
        )

    return approve


@approver
def recording_approver(
    seen: list[ToolCallView], decision: ApprovalDecision = "approve"
) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        seen.append(view)
        return Approval(decision=decision)

    return approve


@approver
def waiting_approver(
    started: anyio.Event,
    cleaned_up: anyio.Event,
    decision: ApprovalDecision = "approve",
) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            cleaned_up.set()
        return Approval(decision=decision)

    return approve


@approver
def gated_approver(
    gate: anyio.Event, decision: ApprovalDecision = "approve"
) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        await gate.wait()
        return Approval(decision=decision)

    return approve


def bash_call() -> ToolCall:
    return ToolCall(id="c1", function="bash", arguments={"cmd": "curl example.com"})


async def decide(
    policies: list[ApprovalPolicy], call: ToolCall | None = None
) -> Approval:
    init_transcript(Transcript())
    approve = policy_approver(policies)
    return await approve("msg", call or bash_call(), ToolCallView(), [])


def events() -> list[ApprovalEvent]:
    return [e for e in transcript().events if isinstance(e, ApprovalEvent)]


def summary() -> ApprovalEvent:
    [event] = [e for e in events() if e.approver == "policy" and e.chain is None]
    return event


async def test_an_unlabelled_list_is_one_chain_and_behaves_as_before() -> None:
    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("escalate"), "*"),
            ApprovalPolicy(fixed_approver("approve"), "*"),
        ]
    )

    assert approval.decision == "approve"
    assert [(e.decision, e.chain) for e in events()] == [
        ("escalate", None),
        ("approve", None),
    ]


async def test_every_chain_covering_the_call_runs() -> None:
    seen: list[ToolCallView] = []

    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("approve"), "*", chain="x"),
            ApprovalPolicy(recording_approver(seen), "*", chain="y"),
        ]
    )

    assert approval.decision == "approve"
    assert len(seen) == 1
    assert summary().metadata == {
        "chains": {
            "x": {"decision": "approve", "explanation": "fixed approve"},
            "y": {"decision": "approve", "explanation": None},
        }
    }


async def test_a_terminate_in_one_chain_wins() -> None:
    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("approve"), "*", chain="x"),
            ApprovalPolicy(fixed_approver("terminate"), "*", chain="y"),
        ]
    )

    assert approval.decision == "terminate"
    assert summary().decision == "terminate"
    assert "y: terminate" in (summary().explanation or "")


async def test_a_reject_does_not_stop_the_other_chain() -> None:
    gate = anyio.Event()

    async def open_gate_after_reject() -> None:
        while not any(e.decision == "reject" for e in events()):
            await anyio.sleep(0.01)
        gate.set()

    init_transcript(Transcript())
    approve = policy_approver(
        [
            ApprovalPolicy(fixed_approver("reject"), "*", chain="x"),
            ApprovalPolicy(gated_approver(gate, "terminate"), "*", chain="y"),
        ]
    )
    async with anyio.create_task_group() as tg:
        tg.start_soon(open_gate_after_reject)
        approval = await approve("msg", bash_call(), ToolCallView(), [])

    assert approval.decision == "terminate"
    metadata = summary().metadata
    assert metadata is not None
    assert metadata["chains"]["y"]["decision"] == "terminate"


async def test_a_terminate_cancels_chains_still_running() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()

    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("terminate"), "*", chain="x"),
            ApprovalPolicy(waiting_approver(started, cleaned_up), "*", chain="y"),
        ]
    )

    assert approval.decision == "terminate"
    assert cleaned_up.is_set()
    metadata = summary().metadata
    assert metadata is not None
    assert metadata["chains"]["y"] == {"decision": "cancelled", "explanation": None}


async def test_escalation_stays_within_its_chain_and_carries_its_reason() -> None:
    seen_x: list[ToolCallView] = []
    seen_y: list[ToolCallView] = []

    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("escalate"), "*", chain="x"),
            ApprovalPolicy(recording_approver(seen_x), "*", chain="x"),
            ApprovalPolicy(recording_approver(seen_y), "*", chain="y"),
        ]
    )

    assert approval.decision == "approve"
    [x_view] = seen_x
    assert x_view.context is not None
    assert 'Escalated by fixed (chain "x"): fixed escalate' in x_view.context.content
    [y_view] = seen_y
    assert y_view.context is None


async def test_an_unanswered_escalation_rejects_only_its_chain() -> None:
    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("escalate"), "*", chain="x"),
            ApprovalPolicy(fixed_approver("approve"), "*", chain="y"),
        ]
    )

    assert approval.decision == "reject"
    [chain_reject] = [e for e in events() if e.approver == "policy" and e.chain == "x"]
    assert chain_reject.decision == "reject"
    assert 'in chain "x"' in (chain_reject.explanation or "")


async def test_a_chain_covering_none_of_the_call_rejects_like_a_lone_chain() -> None:
    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("terminate"), "bash", chain="x"),
            ApprovalPolicy(fixed_approver("approve"), "*", chain="y"),
        ],
        call=ToolCall(id="c2", function="python", arguments={"code": "1"}),
    )

    assert approval.decision == "reject"
    [chain_reject] = [e for e in events() if e.approver == "policy" and e.chain == "x"]
    assert "No approvers registered for tool python" in (chain_reject.explanation or "")
    assert summary().metadata == {
        "chains": {
            "x": {"decision": "reject", "explanation": chain_reject.explanation},
            "y": {"decision": "approve", "explanation": "fixed approve"},
        }
    }


async def test_an_empty_policy_list_rejects() -> None:
    approval = await decide([])

    assert approval.decision == "reject"
    assert "No approvers registered" in (approval.explanation or "")


async def test_modify_across_chains_is_rejected() -> None:
    approval = await decide(
        [
            ApprovalPolicy(fixed_approver("modify"), "*", chain="x"),
            ApprovalPolicy(fixed_approver("approve"), "*", chain="y"),
        ]
    )

    assert approval.decision == "reject"
    assert "modified the call" in (approval.explanation or "")


async def test_modify_from_a_lone_chain_still_works() -> None:
    approval = await decide([ApprovalPolicy(fixed_approver("modify"), "*", chain="x")])

    assert approval.decision == "modify"
    assert approval.modified is not None


def test_the_chain_round_trips_through_config(tmp_path: Path) -> None:
    policies = [
        ApprovalPolicy(fixed_approver("approve"), "*", chain="x"),
        ApprovalPolicy(fixed_approver("approve"), "bash"),
    ]

    config = config_from_approval_policies(policies)

    assert [c.chain for c in config.approvers] == ["x", None]
    assert config.approvers[0].params == {"decision": "approve"}
    yaml = tmp_path / "approval.yaml"
    yaml.write_text(
        "approvers:\n  - name: fixed\n    tools: '*'\n    chain: x\n    decision: terminate\n"
    )
    [policy] = approval_policies_from_config(str(yaml))
    assert policy.chain == "x"
    parsed = ApprovalPolicyConfig(
        approvers=[
            ApproverPolicyConfig.model_validate(
                {"name": "fixed", "tools": "*", "chain": "x", "decision": "terminate"}
            )
        ]
    )
    assert parsed.approvers[0].params == {"decision": "terminate"}
