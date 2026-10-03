from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal, Mapping, NamedTuple

import pytest
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)
from pydantic_core import to_jsonable_python

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai._util.json import json_equal
from inspect_ai._util.registry import registry_log_name
from inspect_ai.agent import Agent, AgentState, agent
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
    policy_approver,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.model import ChatMessage, ChatMessageTool, Model, ModelOutput, get_model
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool._tool import tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_params import ToolParam, ToolParams


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


@approver
def recording_approver(
    calls: list[ToolCall], decision: ApprovalDecision = "approve"
) -> Approver:
    """Approver which records the calls (and views) it is asked to decide on."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        calls.append(call)
        return Approval(decision=decision)

    return approve


async def execute_with_approval(
    call: ToolCall, tools: list[Any], policies: list[ApprovalPolicy]
) -> ChatMessageTool:
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant

    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        tools,
        approval=policies,
    )
    assert isinstance(messages[-1], ChatMessageTool)
    return messages[-1]


async def test_invalid_call_never_reaches_approver() -> None:
    calls: list[ToolCall] = []
    call = ToolCall(id="1", function="addition", arguments={"x": "one", "y": 1})
    message = await execute_with_approval(
        call, [addition()], [ApprovalPolicy(recording_approver(calls), "*")]
    )
    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []


async def test_inexact_conversion_never_reaches_approver() -> None:
    # the schema allows any value, so only the exact-conversion check stops it
    tool_def = ToolDef(
        addition(),
        parameters=ToolParams(properties={"x": ToolParam(), "y": ToolParam()}),
    )
    calls: list[ToolCall] = []
    call = ToolCall(id="1", function="addition", arguments={"x": 1.5, "y": 1})
    message = await execute_with_approval(
        call, [tool_def], [ApprovalPolicy(recording_approver(calls), "*")]
    )
    assert message.error is not None
    assert message.error.type == "parsing"
    assert "Unable to convert '1.5' to int" in message.error.message
    assert calls == []


async def test_viewer_sees_validated_call() -> None:
    viewed: list[ToolCall] = []

    def viewer(call: ToolCall) -> ToolCallView:
        viewed.append(call)
        return ToolCallView()

    tool_def = ToolDef(addition(), viewer=viewer)
    invalid = ToolCall(id="1", function="addition", arguments={"x": "one", "y": 1})
    await execute_with_approval(
        invalid, [tool_def], [ApprovalPolicy(auto_approver(), "*")]
    )
    assert viewed == []

    valid = ToolCall(id="2", function="addition", arguments={"x": 1, "y": 1})
    message = await execute_with_approval(
        valid, [tool_def], [ApprovalPolicy(auto_approver(), "*")]
    )
    assert message.error is None
    assert [call.arguments for call in viewed] == [{"x": 1, "y": 1}]


@approver
def invalid_modifying_approver() -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        modified = ToolCall(
            id=call.id, function=call.function, arguments={"x": "one", "y": 1}
        )
        return Approval(decision="modify", modified=modified)

    return approve


async def test_modified_call_is_validated() -> None:
    call = ToolCall(id="1", function="addition", arguments={"x": 1, "y": 1})
    message = await execute_with_approval(
        call, [addition()], [ApprovalPolicy(invalid_modifying_approver(), "*")]
    )
    assert message.error is not None
    assert message.error.type == "parsing"


async def test_raising_viewer_rejects_call() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    def raising_viewer(call: ToolCall) -> ToolCallView:
        raise KeyError("missing")

    init_transcript(Transcript())
    calls: list[ToolCall] = []
    call = ToolCall(id="1", function="addition", arguments={"x": 1, "y": 1})
    message = await execute_with_approval(
        call,
        [ToolDef(addition(), viewer=raising_viewer)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    # the approver was not asked to decide on a fallback rendering
    assert calls == []
    assert message.error is not None
    assert message.error.type == "approval"
    assert "viewer for tool 'addition' failed" in message.error.message

    # the rejection is in the log
    approvals = [e for e in transcript().events if isinstance(e, ApprovalEvent)]
    assert len(approvals) == 1
    assert approvals[0].decision == "reject"
    assert approvals[0].view is None
    assert approvals[0].explanation is not None
    assert "viewer for tool 'addition' failed" in approvals[0].explanation


def matched_approvers(
    tools: str | list[str], call: ToolCall, other_tools: str | list[str] = "*"
) -> list[str]:
    """Names of the policies `call` is routed to (in order)."""
    import anyio

    matched: list[ToolCall] = []
    other: list[ToolCall] = []
    approve = policy_approver(
        [
            ApprovalPolicy(recording_approver(matched, "escalate"), tools),
            ApprovalPolicy(recording_approver(other, "escalate"), other_tools),
        ]
    )

    async def run() -> None:
        await approve("", call, ToolCallView(), [])

    anyio.run(run)
    return (["matched"] if matched else []) + (["other"] if other else [])


def make_tool_call(function: str, **arguments: Any) -> ToolCall:
    return ToolCall(id="1", function=function, arguments=arguments)


def test_policy_name_glob_ignores_argument_text() -> None:
    # before, the pattern was matched against `type(text='left_click')`
    call = make_tool_call("type", text="left_click")
    assert matched_approvers("*_click", call) == ["other"]
    assert matched_approvers("*_click", make_tool_call("left_click")) == [
        "matched",
        "other",
    ]


def test_policy_name_glob_is_prefix_matched() -> None:
    call = make_tool_call("web_browser_type_submit", text="hello")
    assert matched_approvers("web_browser_type", call) == ["matched", "other"]
    assert matched_approvers("web_browser_go", call) == ["other"]


def test_policy_argument_pattern_documented_syntax() -> None:
    patterns = [
        "computer(action='key'",
        "computer(action='left_click'",
    ]
    assert matched_approvers(
        patterns, make_tool_call("computer", action="key", text="Return")
    ) == ["matched", "other"]
    assert matched_approvers(
        patterns, make_tool_call("computer", action="type", text="key")
    ) == ["other"]
    assert matched_approvers(
        patterns, make_tool_call("computer", action="keyboard")
    ) == ["other"]


def test_policy_argument_pattern_ignores_argument_order() -> None:
    # the model chooses the order of the arguments it sends
    call = make_tool_call("computer", text="Return", action="key")
    assert matched_approvers("computer(action='key'", call) == ["matched", "other"]


def test_policy_argument_pattern_escapes_quotes() -> None:
    # a string value cannot end itself early and complete the pattern
    call = make_tool_call("computer", action="type', mode='safe")
    assert matched_approvers("computer(action='type', mode='safe'", call) == ["other"]
    assert matched_approvers("computer(action='type'", call) == ["other"]
    assert matched_approvers("computer(action='type\\', mode=\\'safe'", call) == [
        "matched",
        "other",
    ]


def test_policy_argument_pattern_needs_function_name() -> None:
    # argument text naming another function does not match its pattern
    call = make_tool_call("python", code="bash(cmd='ls')")
    assert matched_approvers("bash(cmd='ls'", call) == ["other"]
    assert matched_approvers("bash", call) == ["other"]


def test_policy_argument_pattern_closed_and_multiple() -> None:
    call = make_tool_call("bash", cmd="ls", timeout=10)
    assert matched_approvers("bash(cmd='ls')", call) == ["other"]
    assert matched_approvers("bash(cmd='ls', timeout=10)", call) == [
        "matched",
        "other",
    ]
    assert matched_approvers("bash(timeout=10, cmd='ls')", call) == [
        "matched",
        "other",
    ]
    assert matched_approvers("bash(cmd='ls', *)", call) == ["matched", "other"]
    assert matched_approvers("bash(cmd='rm', timeout=10)", call) == ["other"]
    # a comma inside an argument pattern does not split the policy's tool list
    assert matched_approvers("bash(cmd='ls', timeout=10), python", call) == [
        "matched",
        "other",
    ]


def test_policy_argument_pattern_must_be_name_value() -> None:
    import pytest

    with pytest.raises(ValueError, match="expected name=value"):
        policy_approver([ApprovalPolicy(auto_approver(), "computer(*'key'*")])


class Payload(BaseModel):
    amount: float
    note: str = ""


@tool
def typed_inputs(received: list[dict[str, Any]]):
    async def execute(
        when: date | None = None,
        at: datetime | None = None,
        clock: time | None = None,
        payload: Payload | None = None,
        payloads: list[Payload] | None = None,
    ) -> str:
        """Record typed inputs.

        Args:
            when: A date.
            at: A datetime.
            clock: A time.
            payload: A payload.
            payloads: Payloads.
        """
        received.append(
            {
                "when": when,
                "at": at,
                "clock": clock,
                "payload": payload,
                "payloads": payloads,
            }
        )
        return "ok"

    return execute


@pytest.mark.parametrize(
    "arguments",
    [
        {"when": "not-a-date"},
        {"at": "not-a-datetime"},
        {"clock": "25:99"},
        {"payload": {"amount": "x"}},
        {"payload": {"amount": 2**53 + 1}},
        {"payloads": [{"amount": 2**53 + 1}]},
    ],
    ids=["date", "datetime", "time", "model", "model-lossy", "nested-model-lossy"],
)
async def test_inconvertible_call_is_a_parsing_error_before_approval(
    arguments: dict[str, Any],
) -> None:
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript

    init_transcript(Transcript())
    received: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    call = ToolCall(id="1", function="typed_inputs", arguments=arguments)

    # the policy would reject the call, but conversion fails first
    message = await execute_with_approval(
        call,
        [typed_inputs(received)],
        [ApprovalPolicy(recording_approver(calls, "reject"), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []
    assert received == []
    tool_events = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].error is not None
    assert tool_events[0].error.type == "parsing"


async def test_converted_values_match_the_approved_call() -> None:
    received: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    arguments: dict[str, Any] = {
        "when": "2025-01-02",
        "payload": {"amount": 5},
        "payloads": [{"amount": 2**52, "note": "n"}],
    }
    call = ToolCall(id="1", function="typed_inputs", arguments=arguments)

    message = await execute_with_approval(
        call, [typed_inputs(received)], [ApprovalPolicy(recording_approver(calls), "*")]
    )

    assert message.error is None
    # the approver sees each model as it serializes (with its defaults)
    assert [c.arguments for c in calls] == [
        {
            "when": "2025-01-02",
            "payload": {"amount": 5.0, "note": ""},
            "payloads": [{"amount": float(2**52), "note": "n"}],
        }
    ]
    (values,) = received
    assert values["when"] == date(2025, 1, 2)
    assert values["payload"] == Payload(amount=5.0)
    assert values["payloads"] == [Payload(amount=float(2**52), note="n")]


@agent
def amount_agent(received: list[dict[str, Any]]) -> Agent:
    async def execute(
        state: AgentState,
        amount: float,
        payload: Payload | None = None,
        note: str = "",
    ) -> AgentState:
        """Record an amount.

        Args:
            state: Agent state.
            amount: An amount.
            payload: A payload.
            note: A note.
        """
        received.append({"amount": amount, "payload": payload, "note": note})
        return state

    return execute


async def handoff_with_approval(
    arguments: dict[str, Any],
) -> tuple[ChatMessageTool, list[ToolCall], list[dict[str, Any]], int]:
    from inspect_ai.agent import handoff
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser

    received: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    filtered: list[int] = []

    async def input_filter(messages: list[ChatMessage]) -> list[ChatMessage]:
        filtered.append(len(messages))
        return messages

    call = ToolCall(id="1", function="transfer_to_amount_agent", arguments=arguments)
    messages, _ = await execute_tools(
        [
            ChatMessageUser(content="go"),
            ChatMessageAssistant(content="", tool_calls=[call]),
        ],
        [handoff(amount_agent(received), input_filter=input_filter, note="curried")],
        approval=[ApprovalPolicy(recording_approver(calls), "*")],
    )
    tool_messages = [m for m in messages if isinstance(m, ChatMessageTool)]
    return tool_messages[0], calls, received, len(filtered)


async def test_handoff_inexact_argument_never_reaches_approver() -> None:
    message, calls, received, filtered = await handoff_with_approval(
        {"amount": 2**53 + 1}
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []
    assert filtered == 0
    assert received == []


async def test_handoff_arguments_are_converted_for_the_agent() -> None:
    message, calls, received, filtered = await handoff_with_approval(
        {"amount": 5, "payload": {"amount": 1}}
    )

    assert message.error is None
    assert [c.arguments for c in calls] == [
        {"amount": 5, "payload": {"amount": 1.0, "note": ""}}
    ]
    assert filtered == 1
    assert received == [
        {"amount": 5.0, "payload": Payload(amount=1.0), "note": "curried"}
    ]
    assert isinstance(received[0]["amount"], float)


class UnionPayload(BaseModel):
    amount: float | str


class NoneFirstPayload(BaseModel):
    amount: None | float


class AliasPayload(BaseModel):
    amount: float = Field(validation_alias="value")


class ChoicesPayload(BaseModel):
    amount: float = Field(validation_alias=AliasChoices("value", "total"))


class OuterPayload(BaseModel):
    items: list[UnionPayload]


class LiteralPayload(BaseModel):
    amount: float | Literal["unlimited"]


class AnnotatedPayload(BaseModel):
    amount: Annotated[float, Field(gt=0)] | str


class BytesPayload(BaseModel):
    amount: float | bytes


class AnyPayload(BaseModel):
    amount: float | Any


class PathPayload(BaseModel):
    amount: float = Field(validation_alias=AliasPath("values", 0))


class OuterLiteralPayload(BaseModel):
    items: list[LiteralPayload]


class FlagPayload(BaseModel):
    value: bool | bytes


class SetPayload(BaseModel):
    value: Annotated[set[float], Field(min_length=1)] | Literal["none"]


class FrozenSetPayload(BaseModel):
    value: frozenset[float] | Literal["none"]


class OuterFlagPayload(BaseModel):
    items: list[FlagPayload]


class DequePayload(BaseModel):
    value: Annotated[deque[float], Field(min_length=1)] | Literal["none"]


class IntKeyPayload(BaseModel):
    value: Annotated[dict[int, float], Field(min_length=1)] | Literal["none"]


class DateKeyPayload(BaseModel):
    value: Mapping[date, float]


class TupleSetPayload(BaseModel):
    value: frozenset[tuple[date, float]]


@tool
def model_inputs(received: list[dict[str, Any]]):
    async def execute(
        union: UnionPayload | None = None,
        none_first: NoneFirstPayload | None = None,
        alias: AliasPayload | None = None,
        choices: ChoicesPayload | None = None,
        outer: OuterPayload | None = None,
        literal: LiteralPayload | None = None,
        annotated: AnnotatedPayload | None = None,
        raw: BytesPayload | None = None,
        anything: AnyPayload | None = None,
        outer_literal: OuterLiteralPayload | None = None,
        flag: FlagPayload | None = None,
        floats: SetPayload | None = None,
        frozen: FrozenSetPayload | None = None,
        outer_flag: OuterFlagPayload | None = None,
        queue: DequePayload | None = None,
        int_keys: IntKeyPayload | None = None,
        date_keys: DateKeyPayload | None = None,
        tuples: TupleSetPayload | None = None,
    ) -> str:
        """Record model inputs.

        Args:
            union: A union field.
            none_first: An optional field written None first.
            alias: An aliased field.
            choices: A field with alias choices.
            outer: A nested model in a container.
            literal: A union with a Literal member.
            annotated: A union with an annotated member.
            raw: A union with a bytes member.
            anything: A union with an Any member.
            outer_literal: Nested models with a Literal union member.
            flag: A union of a flag and bytes.
            floats: A union with a set of floats.
            frozen: A union with a frozenset of floats.
            outer_flag: Nested flag models.
            queue: A union with a deque of floats.
            int_keys: A union with an int-keyed mapping of floats.
            date_keys: A date-keyed mapping of floats.
            tuples: A frozenset of (date, float) tuples.
        """
        received.append(
            {
                "union": union,
                "none_first": none_first,
                "alias": alias,
                "choices": choices,
                "outer": outer,
                "literal": literal,
                "annotated": annotated,
                "raw": raw,
                "anything": anything,
                "outer_literal": outer_literal,
                "flag": flag,
                "floats": floats,
                "frozen": frozen,
                "outer_flag": outer_flag,
                "queue": queue,
                "int_keys": int_keys,
                "date_keys": date_keys,
                "tuples": tuples,
            }
        )
        return "ok"

    return execute


# fields Inspect converts exactly before the model validates them
PRECONVERTED_CASES: list[tuple[str, dict[str, Any]]] = [
    ("union", {"union": {"amount": 2**53 + 1}}),
    ("none-first", {"none_first": {"amount": 2**53 + 1}}),
    ("alias", {"alias": {"value": 2**53 + 1}}),
    ("alias-choices", {"choices": {"value": 2**53 + 1}}),
    ("nested", {"outer": {"items": [{"amount": 2**53 + 1}]}}),
]

# values the model's own validation changes
CONSTRUCTED_CASES: list[tuple[str, dict[str, Any]]] = [
    ("literal", {"literal": {"amount": 2**53 + 1}}),
    ("annotated", {"annotated": {"amount": 2**53 + 1}}),
    ("bytes", {"raw": {"amount": 2**53 + 1}}),
    ("any", {"anything": {"amount": 2**53 + 1}}),
    ("nested-literal", {"outer_literal": {"items": [{"amount": 2**53 + 1}]}}),
    ("flag-false-string", {"flag": {"value": "false"}}),
    ("flag-true-string", {"flag": {"value": "true"}}),
    ("set", {"floats": {"value": [2**53 + 1]}}),
    ("frozenset", {"frozen": {"value": [2**53 + 1]}}),
    ("nested-flag", {"outer_flag": {"items": [{"value": "false"}]}}),
    ("deque", {"queue": {"value": [2**53 + 1]}}),
    ("int-keys", {"int_keys": {"value": {"1": 2**53 + 1}}}),
    ("date-keys", {"date_keys": {"value": {"2025-01-02": 2**53 + 1}}}),
    ("tuples", {"tuples": {"value": [["2025-01-02", 2**53 + 1]]}}),
]


async def execute_model_inputs(
    arguments: dict[str, Any],
) -> tuple[ChatMessageTool, list[ToolCall], list[ToolCall], list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    viewed: list[ToolCall] = []

    def viewer(call: ToolCall) -> ToolCallView:
        viewed.append(call)
        return ToolCallView()

    message = await execute_with_approval(
        ToolCall(id="1", function="model_inputs", arguments=arguments),
        [ToolDef(model_inputs(received), viewer=viewer)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )
    return message, calls, viewed, received


@pytest.mark.parametrize(
    "arguments",
    [case[1] for case in PRECONVERTED_CASES],
    ids=[case[0] for case in PRECONVERTED_CASES],
)
async def test_inexact_model_field_never_reaches_approval(
    arguments: dict[str, Any],
) -> None:
    message, calls, viewed, received = await execute_model_inputs(arguments)

    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []
    assert viewed == []
    assert received == []


@pytest.mark.parametrize(
    "arguments",
    [case[1] for case in CONSTRUCTED_CASES],
    ids=[case[0] for case in CONSTRUCTED_CASES],
)
async def test_model_field_is_approved_as_constructed(
    arguments: dict[str, Any],
) -> None:
    """A value the model's validation changes is shown to approval as it will run."""
    message, calls, viewed, received = await execute_model_inputs(arguments)

    assert message.error is None
    (values,) = received
    expected = {name: to_jsonable_python(values[name]) for name in arguments}
    assert expected != arguments
    assert [call.arguments for call in calls] == [expected]
    assert [call.arguments for call in viewed] == [expected]


async def test_model_field_lossy_values_are_shown() -> None:
    message, calls, _, _ = await execute_model_inputs(
        {"literal": {"amount": 2**53 + 1}, "flag": {"value": "false"}}
    )

    assert message.error is None
    assert [call.arguments for call in calls] == [
        {"literal": {"amount": float(2**53 + 1)}, "flag": {"value": False}}
    ]


async def test_exact_model_fields_run_as_approved() -> None:
    exact = 2**52
    arguments: dict[str, Any] = {
        "union": {"amount": exact},
        "none_first": {"amount": exact},
        "alias": {"value": exact},
        "choices": {"value": exact},
        "outer": {"items": [{"amount": "text"}, {"amount": exact}]},
        "literal": {"amount": exact},
        "annotated": {"amount": exact},
        "raw": {"amount": exact},
        "anything": {"amount": exact},
        "outer_literal": {"items": [{"amount": "unlimited"}, {"amount": exact}]},
        "flag": {"value": False},
        "floats": {"value": [exact, 1.5]},
        "frozen": {"value": [exact]},
        "outer_flag": {"items": [{"value": True}]},
        "queue": {"value": [exact, 1.5]},
        "int_keys": {"value": {"1": exact, "2": 1.5}},
        "date_keys": {"value": {"2025-01-02": exact}},
        "tuples": {"value": [["2025-01-02", exact], ["2025-01-02", exact]]},
    }

    message, calls, viewed, received = await execute_model_inputs(arguments)

    assert message.error is None
    assert len(viewed) == 1
    (values,) = received
    assert [c.arguments for c in calls] == [
        {name: to_jsonable_python(values[name]) for name in arguments}
    ]
    assert values["union"] == UnionPayload(amount=float(exact))
    assert values["none_first"] == NoneFirstPayload(amount=float(exact))
    assert values["alias"].amount == float(exact)
    assert values["choices"].amount == float(exact)
    assert values["outer"] == OuterPayload(
        items=[UnionPayload(amount="text"), UnionPayload(amount=float(exact))]
    )
    for key in ("literal", "annotated", "raw", "anything"):
        assert values[key].amount == exact
    assert values["outer_literal"] == OuterLiteralPayload(
        items=[LiteralPayload(amount="unlimited"), LiteralPayload(amount=exact)]
    )
    assert values["flag"] == FlagPayload(value=False)
    assert values["floats"].value == {float(exact), 1.5}
    assert values["frozen"].value == frozenset({float(exact)})
    assert values["outer_flag"] == OuterFlagPayload(items=[FlagPayload(value=True)])
    assert values["queue"].value == deque([float(exact), 1.5])
    assert values["int_keys"].value == {1: float(exact), 2: 1.5}
    assert dict(values["date_keys"].value) == {date(2025, 1, 2): float(exact)}
    assert values["tuples"].value == frozenset({(date(2025, 1, 2), float(exact))})


@tool
def path_input(received: list[PathPayload]):
    async def execute(payload: PathPayload) -> str:
        """Record a payload read through an alias path.

        Args:
            payload: The payload.
        """
        received.append(payload)
        return "ok"

    return execute


@pytest.mark.parametrize("amount", [2**53 + 1, 2**52], ids=["inexact", "exact"])
async def test_alias_path_field_is_approved_as_constructed(amount: int) -> None:
    received: list[PathPayload] = []
    calls: list[ToolCall] = []
    tool_def = ToolDef(
        path_input(received),
        parameters=ToolParams(
            properties={"payload": ToolParam()}, required=["payload"]
        ),
    )

    message = await execute_with_approval(
        ToolCall(
            id="1", function="path_input", arguments={"payload": {"values": [amount]}}
        ),
        [tool_def],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is None
    assert [payload.amount for payload in received] == [float(amount)]
    assert [call.arguments for call in calls] == [
        {"payload": {"amount": float(amount)}}
    ]


if __name__ == "__main__":
    test_approve_escalate()


@approver
def modifying_approver(arguments: dict[str, Any]) -> Approver:
    """Approver which replaces the call's arguments."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(id=call.id, function=call.function, arguments=arguments),
        )

    return approve


class Bumped(BaseModel):
    n: int
    note: str = ""

    @field_validator("n")
    @classmethod
    def bump(cls, n: int) -> int:
        return n + 1


class Aliased(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    n: int = Field(alias="N")


class Scaled(BaseModel):
    n: int

    @field_serializer("n")
    def scale(self, n: int) -> int:
        return n * 10


@tool
def model_tool(received: list[Any]):
    async def execute(
        bumped: Bumped | None = None,
        aliased: Aliased | None = None,
        scaled: Scaled | None = None,
    ) -> str:
        """Record models.

        Args:
            bumped: A model whose validator changes its value.
            aliased: A model with an aliased field.
            scaled: A model with a custom serializer.
        """
        received.append(bumped or aliased or scaled)
        return "ok"

    return execute


@pytest.mark.parametrize(
    "initial,modified,runs,expected",
    [
        # unchanged from what was approved: the prepared model runs as it is
        ({"bumped": {"n": 1}}, {"bumped": {"n": 2, "note": ""}}, True, Bumped(n=1)),
        # a changed value that a validator would change again: not run
        ({"bumped": {"n": 1}}, {"bumped": {"n": 5, "note": ""}}, False, None),
        # a changed value that serializes as selected (a model that serializes
        # by alias): runs
        ({"aliased": {"N": 1}}, {"aliased": {"N": 5}}, True, Aliased(N=5)),
        # the approved serialization, unchanged: the prepared model runs
        ({"scaled": {"n": 1}}, {"scaled": {"n": 10}}, True, Scaled(n=1)),
        # a changed value its serializer shows differently: not run
        ({"scaled": {"n": 1}}, {"scaled": {"n": 7}}, False, None),
    ],
    ids=[
        "unchanged",
        "validator-changes-it",
        "alias",
        "serializer-unchanged",
        "serializer-changes-it",
    ],
)
async def test_modified_model_runs_only_as_selected(
    initial: dict[str, Any], modified: dict[str, Any], runs: bool, expected: Any
) -> None:
    received: list[Any] = []
    call = ToolCall(id="1", function="model_tool", arguments=initial)
    message = await execute_with_approval(
        call,
        [model_tool(received)],
        [ApprovalPolicy(modifying_approver(modified), "*")],
    )

    if runs:
        assert message.error is None
        assert received == [expected]
    else:
        assert message.error is not None
        assert message.error.type == "approval"
        assert "changes when it is converted" in message.error.message
        assert received == []


class FieldAlias(BaseModel):
    n: int = Field(alias="N")


class FieldAliasFalse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=False)
    n: int = Field(alias="N")


class FieldAliasTrue(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    n: int = Field(alias="N")


class SerializationAlias(BaseModel):
    n: int = Field(serialization_alias="N")


class SerializationAliasTrue(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)
    n: int = Field(serialization_alias="N")


class NestedAlias(BaseModel):
    inner: FieldAlias
    items: list[SerializationAliasTrue]


@pytest.mark.parametrize(
    "model,payload",
    [
        (FieldAlias, {"N": 1}),
        (FieldAliasFalse, {"N": 1}),
        (FieldAliasTrue, {"N": 1}),
        (SerializationAlias, {"n": 1}),
        (SerializationAliasTrue, {"n": 1}),
        (NestedAlias, {"inner": {"N": 1}, "items": [{"n": 2}]}),
    ],
    ids=[
        "field-alias",
        "field-alias-false",
        "field-alias-true",
        "serialization-alias",
        "serialization-alias-true",
        "nested",
    ],
)
async def test_model_is_approved_as_it_dumps_itself(
    model: Any, payload: dict[str, Any]
) -> None:
    """Approval shows a model as `model_dump(mode="json")` does, aliases included."""
    received: list[Any] = []
    calls: list[ToolCall] = []

    async def execute(value: Any, values: Any = None) -> str:
        received.append((value, values))
        return "ok"

    execute.__annotations__["value"] = model
    execute.__annotations__["values"] = list[model] | None
    tool_def = ToolDef(
        execute,
        name="aliased_tool",
        description="Take a model.",
        parameters=ToolParams(
            properties={"value": ToolParam(), "values": ToolParam()},
            required=["value"],
        ),
    )
    message = await execute_with_approval(
        ToolCall(
            id="1",
            function="aliased_tool",
            arguments={"value": payload, "values": [payload]},
        ),
        [tool_def],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is None
    ((value, values),) = received
    assert [call.arguments for call in calls] == [
        {
            "value": value.model_dump(mode="json"),
            "values": [item.model_dump(mode="json") for item in values],
        }
    ]


BUILDS: list[int] = []


class TextNumber(BaseModel):
    """A model whose serialization changes the JSON type, and that counts builds."""

    n: int

    @field_validator("n")
    @classmethod
    def count(cls, n: int) -> int:
        BUILDS.append(n)
        return n

    @field_serializer("n")
    def as_text(self, n: int) -> str:
        return str(n)


@tool
def labelled_tool(received: list[Any]):
    async def execute(value: TextNumber, label: str) -> str:
        """Record a model and a label.

        Args:
            value: The model.
            label: The label.
        """
        received.append((value, label))
        return "ok"

    return execute


@pytest.mark.parametrize(
    "modified,label",
    [
        ({"value": {"n": "1"}, "label": "after"}, "after"),
        ({"value": {"n": "1"}, "label": "before"}, "before"),
    ],
    ids=["unrelated-argument-changed", "nothing-changed"],
)
async def test_unchanged_model_argument_is_kept_on_modify(
    modified: dict[str, Any], label: str
) -> None:
    """The approved model runs as approved, without being validated or built again."""
    BUILDS.clear()
    received: list[Any] = []
    call = ToolCall(
        id="1",
        function="labelled_tool",
        arguments={"value": {"n": 1}, "label": "before"},
    )
    message = await execute_with_approval(
        call,
        [labelled_tool(received)],
        [ApprovalPolicy(modifying_approver(modified), "*")],
    )

    assert message.error is None
    # built once, for approval; the modification kept it
    assert BUILDS == [1]
    ((value, received_label),) = received
    assert value.n == 1
    assert received_label == label


class ToFlag(BaseModel):
    n: bool | int

    @field_validator("n")
    @classmethod
    def as_flag(cls, n: bool | int) -> bool:
        return bool(n)


class ToNumber(BaseModel):
    n: int | bool

    @field_validator("n")
    @classmethod
    def as_number(cls, n: int | bool) -> int:
        return int(n)


class FlagSerialized(BaseModel):
    n: int

    @field_serializer("n")
    def as_flag(self, n: int) -> bool:
        return bool(n)


@dataclass
class Wrapper:
    value: Bumped


@dataclass
class AliasWrapper:
    value: FieldAliasTrue


class LazyValues(BaseModel):
    values: Iterable[float]


@dataclass
class LazyWrapper:
    value: LazyValues


@pytest.mark.parametrize(
    "model,payload,shown",
    [
        (ToFlag, {"n": 1}, {"n": True}),
        (ToFlag, {"n": 0}, {"n": False}),
        (ToNumber, {"n": True}, {"n": 1}),
        (ToNumber, {"n": False}, {"n": 0}),
        (FlagSerialized, {"n": 1}, {"n": True}),
        (Wrapper, {"value": {"n": 1}}, {"value": {"n": 2, "note": ""}}),
        (AliasWrapper, {"value": {"N": 1}}, {"value": {"N": 1}}),
        (LazyWrapper, {"value": {"values": [1, 2]}}, {"value": {"values": [1.0, 2.0]}}),
    ],
    ids=[
        "to-flag-1",
        "to-flag-0",
        "to-number-true",
        "to-number-false",
        "flag-serializer",
        "dataclass-wrapped-model",
        "dataclass-wrapped-alias",
        "dataclass-wrapped-lazy",
    ],
)
async def test_constructed_value_is_approved_with_its_json_type(
    model: Any, payload: dict[str, Any], shown: dict[str, Any]
) -> None:
    """Approval shows booleans as booleans and numbers as numbers, as constructed."""
    received: list[Any] = []
    calls: list[ToolCall] = []

    async def execute(value: Any, values: Any = None) -> str:
        received.append((value, values))
        return "ok"

    execute.__annotations__["value"] = model
    execute.__annotations__["values"] = list[model] | None
    tool_def = ToolDef(
        execute,
        name="typed_tool",
        description="Take a value.",
        parameters=ToolParams(
            properties={"value": ToolParam(), "values": ToolParam()},
            required=["value"],
        ),
    )
    message = await execute_with_approval(
        ToolCall(
            id="1",
            function="typed_tool",
            arguments={"value": payload, "values": [payload]},
        ),
        [tool_def],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is None
    (call,) = calls
    # json_equal distinguishes JSON booleans from numbers (unlike `==`)
    assert json_equal(call.arguments, {"value": shown, "values": [shown]})
    ((value, values),) = received
    # the tool receives what approval saw
    assert json_equal(to_jsonable_python(value), shown)
    assert json_equal(to_jsonable_python(values[0]), shown)
