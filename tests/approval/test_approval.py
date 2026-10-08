from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any, Literal, NamedTuple

import pytest
from pydantic import BaseModel, field_validator
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
)
from inspect_ai.dataset import Sample
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools
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


# --- approval decides on the validated call that will run --------------------


@approver
def recording_approver(
    calls: list[ToolCall], decision: ApprovalDecision = "approve"
) -> Approver:
    """Approver which records the calls it is asked to decide on."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        calls.append(call)
        return Approval(decision=decision)

    return approve


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


async def execute_with_approval(
    call: ToolCall, tools: list[Any], policies: list[ApprovalPolicy]
) -> ChatMessageTool:
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        tools,
        approval=policies,
    )
    assert isinstance(messages[-1], ChatMessageTool)
    return messages[-1]


@pytest.mark.parametrize(
    "parameters,arguments",
    [
        # fails the schema
        (None, {"x": "one", "y": 1}),
        # passes a loose schema, but would need a lossy conversion (1.5 -> 1)
        (
            ToolParams(properties={"x": ToolParam(), "y": ToolParam()}),
            {"x": 1.5, "y": 1},
        ),
    ],
    ids=["schema", "inexact-conversion"],
)
async def test_invalid_call_never_reaches_approver(
    parameters: ToolParams | None, arguments: dict[str, Any]
) -> None:
    viewed: list[ToolCall] = []

    def viewer(call: ToolCall) -> ToolCallView:
        viewed.append(call)
        return ToolCallView()

    calls: list[ToolCall] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="addition", arguments=arguments),
        [ToolDef(addition(), parameters=parameters, viewer=viewer)],
        [ApprovalPolicy(recording_approver(calls, "reject"), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []
    assert viewed == []


async def test_conversion_error_is_a_parsing_error_before_approval() -> None:
    """A value the schema allows but that cannot be converted fails before approval."""

    @tool
    def schedule():
        async def execute(when: date) -> str:
            """Schedule something.

            Args:
                when: The date.
            """
            return "ok"

        return execute

    calls: list[ToolCall] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="schedule", arguments={"when": "not-a-date"}),
        [schedule()],
        [ApprovalPolicy(recording_approver(calls, "reject"), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []


async def test_modified_call_is_validated() -> None:
    message = await execute_with_approval(
        ToolCall(id="1", function="addition", arguments={"x": 1, "y": 1}),
        [addition()],
        [ApprovalPolicy(modifying_approver({"x": "one", "y": 1}), "*")],
    )
    assert message.error is not None
    assert message.error.type == "parsing"


class Step(BaseModel):
    step: str
    status: Literal["pending", "done"] = "pending"


class Bumped(BaseModel):
    n: int

    @field_validator("n")
    @classmethod
    def bump(cls, n: int) -> int:
        return n + 1


class Flag(BaseModel):
    n: bool | int

    @field_validator("n")
    @classmethod
    def as_flag(cls, n: bool | int) -> bool:
        return bool(n)


class Lazy(BaseModel):
    values: Iterable[int]


class Parent(BaseModel):
    children: list[Lazy]


@tool
def model_tool(received: list[Any]):
    async def execute(
        step: Step | None = None,
        steps: list[Step] | None = None,
        either: Step | dict[str, Any] | None = None,
        bumped: Bumped | None = None,
        flag: Flag | None = None,
        by_name: dict[str, Step] | None = None,
        parent: Parent | None = None,
    ) -> str:
        """Record models.

        Args:
            step: A model.
            steps: A list of models.
            either: A model or a plain object.
            bumped: A model whose validator changes its value.
            flag: A model whose validator turns a number into a flag.
            by_name: Models in a mapping (not supported under approval).
            parent: A model holding lazy values (not supported under approval).
        """
        received.append(
            {
                k: v
                for k, v in dict(
                    step=step,
                    steps=steps,
                    either=either,
                    bumped=bumped,
                    flag=flag,
                    by_name=by_name,
                    parent=parent,
                ).items()
                if v is not None
            }
        )
        return "ok"

    return execute


@pytest.mark.parametrize(
    "arguments,shown",
    [
        ({"step": {"step": "plan"}}, {"step": {"step": "plan", "status": "pending"}}),
        (
            {"steps": [{"step": "plan"}, {"step": "act", "status": "done"}]},
            {
                "steps": [
                    {"step": "plan", "status": "pending"},
                    {"step": "act", "status": "done"},
                ]
            },
        ),
        ({"either": {"other": 1}}, {"either": {"other": 1}}),
        ({"bumped": {"n": 1}}, {"bumped": {"n": 2}}),
        ({"flag": {"n": 1}}, {"flag": {"n": True}}),
    ],
    ids=["model", "list-of-models", "model-or-dict", "validator", "flag-validator"],
)
async def test_model_parameter_is_approved_as_it_runs(
    arguments: dict[str, Any], shown: dict[str, Any]
) -> None:
    """The approver sees each model as it serializes, and that instance runs."""
    received: list[Any] = []
    calls: list[ToolCall] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments=arguments),
        [model_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is None
    (call,) = calls
    # json_equal tells a JSON true from 1, which `==` does not
    assert json_equal(call.arguments, shown)
    (values,) = received
    assert json_equal(to_jsonable_python(values), shown)


@pytest.mark.parametrize(
    "arguments,runs",
    [
        (
            {"by_name": {"a": {"step": "plan"}}},
            {"by_name": {"a": {"step": "plan", "status": "pending"}}},
        ),
        (
            {"parent": {"children": [{"values": [1, 2]}]}},
            {"parent": {"children": [{"values": [1, 2]}]}},
        ),
    ],
    ids=["mapping", "nested-lazy"],
)
async def test_model_in_unsupported_form_errors_under_approval(
    arguments: dict[str, Any], runs: dict[str, Any]
) -> None:
    received: list[Any] = []
    calls: list[ToolCall] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments=arguments),
        [model_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert "does not support" in message.error.message
    assert calls == []

    # without approval the tool runs as before, with its lazy values unconsumed
    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content=[],
                tool_calls=[
                    ToolCall(id="2", function="model_tool", arguments=arguments)
                ],
            )
        ],
        [model_tool(received)],
    )
    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is None
    assert to_jsonable_python(received) == [runs]


@pytest.mark.parametrize(
    "modified,runs",
    [
        # the approver selects n=2 (as shown), which the validator would run as 3
        ({"bumped": {"n": 2}}, False),
        # a model that serializes as selected runs
        ({"step": {"step": "act", "status": "pending"}}, True),
    ],
    ids=["validator-changes-it", "serializes-as-selected"],
)
async def test_modified_model_runs_only_as_selected(
    modified: dict[str, Any], runs: bool
) -> None:
    received: list[Any] = []
    initial = {
        name: {"step": "plan"} if name == "step" else {"n": 1} for name in modified
    }
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments=initial),
        [model_tool(received)],
        [ApprovalPolicy(modifying_approver(modified), "*")],
    )

    if runs:
        assert message.error is None
        assert json_equal(to_jsonable_python(received), [modified])
    else:
        assert message.error is not None
        assert message.error.type == "approval"
        assert received == []


@agent
def amount_agent(received: list[dict[str, Any]]) -> Agent:
    async def execute(state: AgentState, amount: float, note: str = "") -> AgentState:
        """Record an amount.

        Args:
            state: Agent state.
            amount: An amount.
            note: A note.
        """
        received.append({"amount": amount, "note": note})
        return state

    return execute


@pytest.mark.parametrize("amount,valid", [(2**53 + 1, False), (5, True)])
async def test_handoff_arguments_are_converted_before_approval(
    amount: int, valid: bool
) -> None:
    from inspect_ai.agent import handoff

    received: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    call = ToolCall(
        id="1", function="transfer_to_amount_agent", arguments={"amount": amount}
    )
    messages, _ = await execute_tools(
        [
            ChatMessageUser(content="go"),
            ChatMessageAssistant(content="", tool_calls=[call]),
        ],
        [handoff(amount_agent(received), note="curried")],
        approval=[ApprovalPolicy(recording_approver(calls), "*")],
    )
    (message,) = [m for m in messages if isinstance(m, ChatMessageTool)]

    if valid:
        assert message.error is None
        assert received == [{"amount": 5.0, "note": "curried"}]
        assert isinstance(received[0]["amount"], float)
    else:
        assert message.error is not None
        assert message.error.type == "parsing"
        assert calls == []
        assert received == []


if __name__ == "__main__":
    test_approve_escalate()
