from pathlib import Path
from typing import NamedTuple, cast

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai._util.registry import registry_log_name
from inspect_ai.approval import (
    Approval,
    ApprovalDecision,
    ApprovalPolicy,
    Approver,
    approval,
    approver,
    auto_approver,
    read_approval_policies,
)
from inspect_ai.approval._policy import (
    ApprovalPolicyConfig,
    ApproverPolicyConfig,
    approval_policies_from_config,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool._tool import tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallView


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


class ApprovalEval(NamedTuple):
    log: EvalLog
    task: Task


def resolve_policy(
    policy: str | ApprovalPolicy | list[ApprovalPolicy] | None,
) -> str | list[ApprovalPolicy] | None:
    if policy is None:
        return None

    if isinstance(policy, str):
        return (Path(__file__).parent / policy).as_posix()

    return policy if isinstance(policy, list) else [policy]


def approval_model() -> Model:
    # mockllm consumes custom_outputs as a one-shot iterator, so don't memoize
    # (tests which run two evals need a fresh model for each)
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="addition",
                tool_arguments={"x": 1, "y": 1},
            ),
            ModelOutput.from_content("mockllm/model", content="2"),
        ],
        memoize=False,
    )


def approval_task(
    task_policy: str | ApprovalPolicy | list[ApprovalPolicy] | None = None,
) -> Task:
    return Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        scorer=match(numeric=True),
        approval=resolve_policy(task_policy),
    )


def eval_with_approval(
    policy: str | ApprovalPolicy | list[ApprovalPolicy] | None = None,
    task_policy: str | ApprovalPolicy | list[ApprovalPolicy] | None = None,
) -> ApprovalEval:
    task = approval_task(task_policy)

    return ApprovalEval(
        eval(task, model=approval_model(), approval=resolve_policy(policy))[0], task
    )


def check_approval(
    policy: str | ApprovalPolicy | list[ApprovalPolicy] | None,
    decision: ApprovalDecision,
    approver: str = "auto",
    task_policy: str | ApprovalPolicy | list[ApprovalPolicy] | None = None,
) -> ApprovalEvent:
    log = eval_with_approval(policy, task_policy).log

    approval = find_approval(log)
    assert approval
    assert approval.approver == approver
    assert approval.decision == decision

    return approval


approve_all_policy = ApprovalPolicy(approver=auto_approver(), tools="*")
reject_all_policy = ApprovalPolicy(approver=auto_approver("reject"), tools="*")
reject_all_config = ApprovalPolicyConfig(
    approvers=[
        ApproverPolicyConfig(name="auto", tools="*", params={"decision": "reject"})
    ]
)


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


def test_task_approval_recorded_in_config():
    log = eval_with_approval(task_policy=reject_all_policy).log
    assert log.eval.config.approval == reject_all_config


def test_task_approval_config_file_recorded_in_config():
    log = eval_with_approval(task_policy="reject.yaml").log
    approval = log.eval.config.approval
    assert approval
    assert [(a.name, a.tools, a.params) for a in approval.approvers] == [
        ("auto", "foo*", {"decision": "reject"}),
        ("auto", "*", {"decision": "escalate"}),
        ("auto", ["foo*", "add*"], {"decision": "reject"}),
    ]


def test_eval_approval_takes_precedence_in_config():
    result = eval_with_approval(
        policy=reject_all_policy, task_policy=approve_all_policy
    )
    assert result.log.eval.config.approval == reject_all_config
    # the merge runs against a copy, so the caller's task keeps its own policy
    assert result.task.approval == [approve_all_policy]
    approval = find_approval(result.log)
    assert approval and approval.decision == "reject"


def test_eval_approval_not_leaked_to_reused_task():
    task = approval_task()

    first = eval(task, model=approval_model(), approval=[reject_all_policy])[0]
    assert first.eval.config.approval == reject_all_config
    first_approval = find_approval(first)
    assert first_approval and first_approval.decision == "reject"

    second = eval(task, model=approval_model())[0]
    assert second.eval.config.approval is None
    assert find_approval(second) is None


def test_no_approval_recorded_in_config():
    assert eval_with_approval().log.eval.config.approval is None


def test_approve_config():
    check_approval("approve.yaml", decision="approve")


def test_read_approval_policies_file_uri():
    policy_file = (Path(__file__).parent / "approve.yaml").as_uri()

    policies = read_approval_policies(policy_file)

    assert [policy.tools for policy in policies] == [
        "foo*",
        "*",
        ["foo*", "add*"],
    ]


def test_approval_policies_from_config_percent_encoded_file_uri(tmp_path: Path):
    # Path.as_uri() percent-encodes the space in the directory name
    policy_dir = tmp_path / "my policies"
    policy_dir.mkdir()
    policy_file = policy_dir / "approve.yaml"
    policy_file.write_text(
        'approvers:\n  - name: auto\n    tools: "*"\n    decision: approve\n'
    )

    policies = approval_policies_from_config(policy_file.as_uri())

    assert len(policies) == 1
    assert policies[0].tools == "*"
    assert registry_log_name(policies[0].approver) == "auto"


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


def test_approval_context_manager():
    from inspect_ai.approval._apply import _tool_approver

    # no approver set initially
    assert _tool_approver.get(None) is None

    # context manager sets and restores approver
    with approval([approve_all_policy]):
        assert _tool_approver.get(None) is not None
    assert _tool_approver.get(None) is None

    # nested contexts
    with approval([approve_all_policy]):
        outer_approver = _tool_approver.get(None)
        assert outer_approver is not None
        with approval([reject_all_policy]):
            inner_approver = _tool_approver.get(None)
            assert inner_approver is not None
            assert inner_approver is not outer_approver
        # outer restored
        assert _tool_approver.get(None) is outer_approver
    # fully restored
    assert _tool_approver.get(None) is None


async def test_execute_tools_approval():
    """execute_tools with approval=[reject_all] should reject tool calls."""
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
    from inspect_ai.tool._tool_call import ToolCall
    from inspect_ai.tool._tool_def import ToolDef

    tool_def = ToolDef(addition())
    call = ToolCall(
        id="test",
        function="addition",
        arguments={"x": 1, "y": 1},
        parse_error=None,
    )
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [tool_def],
        approval=[reject_all_policy],
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is not None
    assert messages[-1].error.type == "approval"


async def test_execute_tools_approval_empty_list():
    """execute_tools with approval=[] should behave like None (no approval)."""
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
    from inspect_ai.tool._tool_call import ToolCall
    from inspect_ai.tool._tool_def import ToolDef

    tool_def = ToolDef(addition())
    call = ToolCall(
        id="test",
        function="addition",
        arguments={"x": 1, "y": 1},
        parse_error=None,
    )
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [tool_def],
        approval=[],
    )

    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is None
    assert messages[-1].content == [ContentText(text="2")]


async def test_execute_tools_reject_records_tool_event():
    """A rejected tool call must still emit a ToolEvent with error.type='approval'."""
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_call import ToolCall
    from inspect_ai.tool._tool_def import ToolDef

    init_transcript(Transcript())

    tool_def = ToolDef(addition())
    call = ToolCall(
        id="test",
        function="addition",
        arguments={"x": 1, "y": 1},
        parse_error=None,
    )
    await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [tool_def],
        approval=[reject_all_policy],
    )

    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].id == "test"
    assert tool_events[0].function == "addition"
    assert tool_events[0].error is not None
    assert tool_events[0].error.type == "approval"


async def test_execute_tools_terminate_records_tool_event():
    """A terminated tool call must still emit a ToolEvent (failed=True) before raising."""
    import pytest

    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_call import ToolCall
    from inspect_ai.tool._tool_def import ToolDef

    init_transcript(Transcript())

    terminate_all_policy = ApprovalPolicy(
        approver=auto_approver("terminate"), tools="*"
    )

    tool_def = ToolDef(addition())
    call = ToolCall(
        id="test",
        function="addition",
        arguments={"x": 1, "y": 1},
        parse_error=None,
    )
    with pytest.raises(TerminateSampleError):
        await execute_tools(
            [ChatMessageAssistant(content=[], tool_calls=[call])],
            [tool_def],
            approval=[terminate_all_policy],
        )

    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].id == "test"
    assert tool_events[0].function == "addition"
    assert tool_events[0].failed is True


async def test_execute_tools_parse_error_records_tool_event():
    """A ToolCall with parse_error must emit a ToolEvent with error.type='parsing'."""
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_call import ToolCall
    from inspect_ai.tool._tool_def import ToolDef

    init_transcript(Transcript())

    tool_def = ToolDef(addition())
    call = ToolCall(
        id="test",
        function="addition",
        arguments={"x": 1, "y": 1},
        parse_error="bad arguments",
    )
    await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [tool_def],
    )

    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].id == "test"
    assert tool_events[0].error is not None
    assert tool_events[0].error.type == "parsing"


async def test_execute_tools_tool_not_found_records_tool_event():
    """A call to an unregistered tool must emit a ToolEvent with error.type='parsing'."""
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_call import ToolCall
    from inspect_ai.tool._tool_def import ToolDef

    init_transcript(Transcript())

    tool_def = ToolDef(addition())
    call = ToolCall(
        id="test",
        function="nonexistent",
        arguments={},
        parse_error=None,
    )
    await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [tool_def],
    )

    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].function == "nonexistent"
    assert tool_events[0].error is not None
    assert tool_events[0].error.type == "parsing"


@approver
def generating_approver() -> Approver:
    """Approver which consults a model before approving."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        await get_model("mockllm/model").generate("Should this call be approved?")
        return Approval(decision="approve")

    return approve


async def test_approver_inference_exempt_from_limits():
    """Model inference within an approver shouldn't consume the agent's budget."""
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool
    from inspect_ai.tool._tool_def import ToolDef
    from inspect_ai.util._limit import token_limit, turn_limit

    tool_def = ToolDef(addition())
    call = ToolCall(id="test", function="addition", arguments={"x": 1, "y": 1})

    with token_limit(1_000_000) as tokens, turn_limit(10) as turns:
        messages, _ = await execute_tools(
            [ChatMessageAssistant(content=[], tool_calls=[call])],
            [tool_def],
            approval=[ApprovalPolicy(approver=generating_approver(), tools="*")],
        )

    # the tool call was approved (i.e. the approver did generate)
    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is None

    # ...but its generation was not metered
    assert tokens.usage == 0
    assert turns.usage == 0


def test_approval_policy_comma_separated_tools():
    policy = ApprovalPolicy(
        approver=auto_approver(), tools="web_browser*, addition, python"
    )
    check_approval(policy, decision="approve")


def test_approval_policy_comma_separated_list():
    policy = ApprovalPolicy(
        approver=auto_approver(), tools=["web_browser*", "addition, python"]
    )
    check_approval(policy, decision="approve")


# ---------------------------------------------------------------------------
# result-stage approval
# ---------------------------------------------------------------------------


def result_policy(
    decision: ApprovalDecision = "approve", tools: str | list[str] = "*"
) -> ApprovalPolicy:
    return ApprovalPolicy(auto_approver(decision), tools, stage="result")


def addition_call(id: str = "test") -> ToolCall:
    return ToolCall(id=id, function="addition", arguments={"x": 1, "y": 1})


async def execute_addition(
    approval: list[ApprovalPolicy], *calls: ToolCall, parallel: bool = False
) -> list[ChatMessage]:
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_def import ToolDef

    init_transcript(Transcript())
    calls = calls or (addition_call(),)
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=list(calls))],
        [ToolDef(addition(), parallel=parallel)],
        approval=approval,
    )
    return messages


def approval_events(log: EvalLog) -> list[ApprovalEvent]:
    assert log.samples
    return [e for e in log.samples[0].events if isinstance(e, ApprovalEvent)]


def tool_message(messages: list[ChatMessage]) -> ChatMessageTool:
    return next(m for m in messages if isinstance(m, ChatMessageTool))


def test_result_approve_passes_result_through():
    log = eval_with_approval(result_policy("approve")).log

    assert log.samples
    assert tool_message(log.samples[0].messages).content == [ContentText(text="2")]
    events = approval_events(log)
    assert [(e.stage, e.decision) for e in events] == [("result", "approve")]


def test_result_approval_is_recorded_after_the_tool_event():
    from inspect_ai.event._tool import ToolEvent

    log = eval_with_approval(result_policy("approve")).log

    assert log.samples
    events = log.samples[0].events
    tool_index = next(i for i, e in enumerate(events) if isinstance(e, ToolEvent))
    approval_index = next(
        i for i, e in enumerate(events) if isinstance(e, ApprovalEvent)
    )
    assert approval_index > tool_index


def test_result_reject_withholds_result_from_model():
    from inspect_ai.event._tool import ToolEvent

    log = eval_with_approval(result_policy("reject")).log

    assert log.samples
    message = tool_message(log.samples[0].messages)
    assert message.error is not None
    assert message.error.type == "approval"
    assert message.error.message == "Automatic decision."
    assert message.content == ""
    # the log keeps what the tool actually returned
    tool_event = next(e for e in log.samples[0].events if isinstance(e, ToolEvent))
    assert tool_event.result == [ContentText(text="2")]
    assert tool_event.error is None
    assert approval_events(log)[-1].decision == "reject"
    assert approval_events(log)[-1].stage == "result"


def test_result_policies_leave_call_stage_unapproved():
    log = eval_with_approval(result_policy("approve")).log

    # with no call-stage policy the call runs without a call-stage decision
    assert [e.stage for e in approval_events(log)] == ["result"]


def test_call_policies_do_not_review_results():
    log = eval_with_approval(approve_all_policy).log

    assert [e.stage for e in approval_events(log)] == ["call"]


def test_both_stages_apply_in_order():
    log = eval_with_approval([approve_all_policy, result_policy("reject")]).log

    assert [(e.stage, e.decision) for e in approval_events(log)] == [
        ("call", "approve"),
        ("result", "reject"),
    ]


def test_call_rejected_is_not_reviewed_at_result_stage():
    seen: list[ToolCall] = []
    log = eval_with_approval(
        [reject_all_policy, ApprovalPolicy(recording_approver(seen), "*", "result")]
    ).log

    assert seen == []
    assert [(e.stage, e.decision) for e in approval_events(log)] == [("call", "reject")]


def test_result_unmatched_tool_is_rejected_by_policy():
    approval = check_approval(
        result_policy("approve", tools="foo*"), decision="reject", approver="policy"
    )

    assert approval.stage == "result"
    assert approval.explanation == (
        "No approvers registered for the result of tool addition"
    )


def test_result_escalate_falls_through_to_next_policy():
    approval = check_approval(
        [result_policy("escalate", tools="add*"), result_policy("approve")],
        decision="approve",
    )

    assert approval.stage == "result"


async def test_result_terminate_terminates_after_recording_the_result():
    import pytest

    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import transcript

    with pytest.raises(TerminateSampleError):
        await execute_addition([result_policy("terminate")])

    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].pending is None
    assert tool_events[0].result == [ContentText(text="2")]
    assert tool_events[0].failed is True


async def test_result_terminate_with_parallel_sibling_finalises_both_events():
    import pytest

    from inspect_ai._util.exception import TerminateSampleError
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import transcript

    with pytest.raises(TerminateSampleError):
        await execute_addition(
            [result_policy("terminate")],
            addition_call("a"),
            addition_call("b"),
            parallel=True,
        )

    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert sorted(e.id for e in tool_events) == ["a", "b"]
    assert all(e.pending is None for e in tool_events)


async def test_result_modify_is_an_error():
    import pytest

    with pytest.raises(RuntimeError, match="cannot be modified"):
        await execute_addition([result_policy("modify")])


@approver
def recording_approver(seen: list[ToolCall]) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        seen.append(call)
        return Approval(decision="approve")

    return approve


@approver
def history_recording_approver(seen: list[list[ChatMessage]]) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        seen.append(list(history))
        return Approval(decision="approve")

    return approve


async def test_result_approver_sees_the_result_at_the_end_of_history():
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool

    seen: list[list[ChatMessage]] = []

    await execute_addition(
        [ApprovalPolicy(history_recording_approver(seen), "*", stage="result")]
    )

    assert len(seen) == 1
    assert isinstance(seen[0][-2], ChatMessageAssistant)
    assert isinstance(seen[0][-1], ChatMessageTool)
    assert seen[0][-1].tool_call_id == "test"
    assert seen[0][-1].content == [ContentText(text="2")]


async def test_result_approver_inference_exempt_from_limits():
    from inspect_ai.util._limit import token_limit, turn_limit

    with token_limit(1_000_000) as tokens, turn_limit(10) as turns:
        messages = await execute_addition(
            [ApprovalPolicy(generating_approver(), "*", stage="result")]
        )

    assert tool_message(messages).error is None
    assert tokens.usage == 0
    assert turns.usage == 0


def test_result_stage_config():
    log = eval_with_approval(task_policy="result.yaml").log

    assert log.samples
    assert tool_message(log.samples[0].messages).error is not None
    assert [(e.stage, e.decision) for e in approval_events(log)] == [
        ("call", "approve"),
        ("result", "reject"),
    ]
    assert log.eval.config.approval
    assert [(a.tools, a.stage) for a in log.eval.config.approval.approvers] == [
        ("*", "call"),
        ("add*", "result"),
    ]


def test_result_stage_recorded_in_config():
    log = eval_with_approval(task_policy=result_policy("reject", "add*")).log

    assert log.eval.config.approval == ApprovalPolicyConfig(
        approvers=[
            ApproverPolicyConfig(
                name="auto", tools="add*", params={"decision": "reject"}, stage="result"
            )
        ]
    )


def test_read_approval_policies_stage():
    policies = read_approval_policies(
        (Path(__file__).parent / "result.yaml").as_posix()
    )

    assert [policy.stage for policy in policies] == ["call", "result"]


async def test_result_stage_skips_calls_that_never_executed():
    """A parsing failure is the model's feedback; it is not a result to review."""
    seen: list[ToolCall] = []

    messages = await execute_addition(
        [ApprovalPolicy(recording_approver(seen), "*", stage="result")],
        ToolCall(id="test", function="nonexistent", arguments={}),
    )

    assert seen == []
    assert tool_message(messages).error is not None
    assert tool_message(messages).error.type == "parsing"


async def test_result_stage_skips_handoffs():
    """A handoff's result is a transfer notice; the sub-agent's calls are reviewed."""
    from inspect_ai.agent import Agent, AgentState, agent, handoff
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_def import ToolDef

    @agent
    def helper() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            state.messages.append(ChatMessageAssistant(content="helper says hi"))
            return state

        return execute

    seen: list[ToolCall] = []
    init_transcript(Transcript())

    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content=[],
                tool_calls=[
                    ToolCall(id="test", function="transfer_to_helper", arguments={})
                ],
            )
        ],
        [ToolDef(handoff(helper(), description="A helper agent."))],
        approval=[ApprovalPolicy(recording_approver(seen), "*", stage="result")],
    )

    assert seen == []
    assert tool_message(messages).error is None
    assert any("helper says hi" in m.text for m in messages)


@approver
def modifying_approver(x: int) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        modified = ToolCall(
            id=call.id, function=call.function, arguments={**call.arguments, "x": x}
        )
        return Approval(decision="modify", modified=modified)

    return approve


async def test_result_stage_sees_the_call_as_modified_at_the_call_stage():
    seen: list[ToolCall] = []

    messages = await execute_addition(
        [
            ApprovalPolicy(modifying_approver(5), "*"),
            ApprovalPolicy(recording_approver(seen), "*", stage="result"),
        ]
    )

    assert tool_message(messages).content == [ContentText(text="6")]
    assert [call.arguments for call in seen] == [{"x": 5, "y": 1}]


async def test_result_stage_skips_a_handoff_that_failed():
    from inspect_ai.agent import Agent, AgentState, agent, handoff
    from inspect_ai.log._transcript import Transcript, init_transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool import ToolError
    from inspect_ai.tool._tool_def import ToolDef

    @agent
    def failing_helper() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            raise ToolError("helper broke")

        return execute

    seen: list[ToolCall] = []
    init_transcript(Transcript())

    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content=[],
                tool_calls=[
                    ToolCall(
                        id="test", function="transfer_to_failing_helper", arguments={}
                    )
                ],
            )
        ],
        [ToolDef(handoff(failing_helper(), description="A failing helper."))],
        approval=[ApprovalPolicy(recording_approver(seen), "*", stage="result")],
    )

    assert seen == []
    error = tool_message(messages).error
    assert error is not None
    assert error.message == "helper broke"


@approver
def state_approver() -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, state: object
    ) -> Approval:
        return Approval(decision="approve")

    # the deprecated signature deliberately does not satisfy the protocol
    return cast(Approver, approve)


async def test_deprecated_state_approver_is_rejected_at_the_result_stage():
    import pytest

    with pytest.raises(ValueError, match="cannot be used at the result stage"):
        await execute_addition([ApprovalPolicy(state_approver(), "*", stage="result")])


async def test_result_reject_with_parallel_siblings_keeps_declared_order():
    messages = await execute_addition(
        [result_policy("reject", tools="addition(x=2*"), result_policy("approve")],
        ToolCall(id="a", function="addition", arguments={"x": 1, "y": 1}),
        ToolCall(id="b", function="addition", arguments={"x": 2, "y": 2}),
        ToolCall(id="c", function="addition", arguments={"x": 3, "y": 3}),
        parallel=True,
    )

    results = [m for m in messages if isinstance(m, ChatMessageTool)]
    assert [m.tool_call_id for m in results] == ["a", "b", "c"]
    assert [m.error is not None for m in results] == [False, True, False]
    assert results[2].content == [ContentText(text="6")]


async def test_approval_context_manager_empty_list_still_rejects():
    """approval([]) has always meant "no approvers registered": every call rejected."""
    from inspect_ai.approval._apply import _tool_result_approver

    with approval([]):
        assert _tool_result_approver.get(None) is None
        messages = await execute_addition([])

    assert tool_message(messages).error is not None
    assert tool_message(messages).error.type == "approval"


def test_approval_event_without_stage_reads_as_call_stage():
    """Logs written before the stage field existed are call-stage approvals."""
    event = ApprovalEvent.model_validate(
        {
            "event": "approval",
            "message": "",
            "call": {"id": "test", "function": "addition", "arguments": {}},
            "approver": "auto",
            "decision": "approve",
        }
    )

    assert event.stage == "call"


def test_approval_context_manager_replaces_only_declared_stages():
    from inspect_ai.approval._apply import _tool_approver, _tool_result_approver

    assert _tool_result_approver.get(None) is None

    with approval([approve_all_policy]):
        outer_call = _tool_approver.get(None)
        assert outer_call is not None
        assert _tool_result_approver.get(None) is None
        with approval([result_policy()]):
            # a result-only context leaves the surrounding call-stage policy in force
            assert _tool_approver.get(None) is outer_call
            assert _tool_result_approver.get(None) is not None
        assert _tool_approver.get(None) is outer_call
        assert _tool_result_approver.get(None) is None

    assert _tool_approver.get(None) is None
    assert _tool_result_approver.get(None) is None


async def test_result_only_context_keeps_ambient_call_stage_rejection():
    with approval([reject_all_policy]):
        messages = await execute_addition([result_policy("approve")])

    assert tool_message(messages).error is not None
    assert tool_message(messages).error.type == "approval"


if __name__ == "__main__":
    test_approve_escalate()
