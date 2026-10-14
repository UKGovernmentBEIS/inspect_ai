import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from itertools import count
from pathlib import Path
from typing import Any, Literal, NamedTuple

import pytest
from pydantic import BaseModel, Field, computed_field, field_serializer, field_validator
from pydantic.dataclasses import dataclass as pydantic_dataclass
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
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
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
from inspect_ai.tool._tool import Tool, tool
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


@tool
def echo(calls: list[str]) -> Tool:
    async def execute(text: str) -> str:
        """
        Echo text back.

        Args:
            text (str): Text to echo.

        Returns:
            The text.
        """
        calls.append(text)
        return text

    return execute


@approver
def modifying_approver(arguments: dict[str, object], function: str = "") -> Approver:
    """Approver which modifies each call's arguments (and its function, if given)."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id, function=function or call.function, arguments=arguments
            ),
        )

    return approve


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


@pydantic_dataclass
class Doubled:
    x: int

    @field_validator("x")
    @classmethod
    def double(cls, x: int) -> int:
        return x * 2


@dataclass
class Normalized:
    name: str
    size: int = 7

    def __post_init__(self) -> None:
        self.name = self.name.lower()


@dataclass
class Outer:
    inner: Normalized


class Holder(BaseModel):
    inner: Normalized


@dataclass
class Wrapper:
    step: Step


class Guarded(BaseModel):
    flags: dict[str, bool]

    @field_validator("flags", mode="before")
    @classmethod
    def force_write(cls, flags: Any) -> Any:
        flags["write"] = True
        return flags


@dataclass
class GuardedData:
    flags: Any

    def __post_init__(self) -> None:
        self.flags["write"] = True


_ids = count()


@dataclass
class Counted:
    name: str
    id: int = field(default_factory=lambda: next(_ids))


@pydantic_dataclass
class PydanticCounted:
    name: str
    id: int = Field(default_factory=lambda: next(_ids))


class Aliased(BaseModel):
    file_path: str = Field(alias="filePath")

    @computed_field
    def name(self) -> str:
        return Path(self.file_path).name


class SplitAlias(BaseModel):
    value: str = Field(validation_alias="in_value", serialization_alias="out_value")


class Unserializable(BaseModel):
    value: str

    @field_serializer("value")
    def fail(self, value: str) -> str:
        raise ValueError("cannot serialize")


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
        aliased: Aliased | None = None,
        split_alias: SplitAlias | None = None,
        unserializable: Unserializable | None = None,
        doubled: Doubled | None = None,
        normalized: Normalized | None = None,
        outer: Outer | None = None,
        holder: Holder | None = None,
        wrapper: Wrapper | None = None,
        outers: list[Outer] | None = None,
        guarded: Guarded | None = None,
        guarded_data: GuardedData | None = None,
        counted: Counted | None = None,
        pydantic_counted: PydanticCounted | None = None,
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
            aliased: A model with an alias and a computed field.
            split_alias: A model that serializes under another alias.
            unserializable: A model whose serializer fails.
            doubled: A Pydantic dataclass whose validator changes its value.
            normalized: A dataclass whose `__post_init__` changes its value.
            outer: A dataclass holding a dataclass.
            holder: A model holding a dataclass.
            wrapper: A dataclass holding a model.
            outers: A list of dataclasses holding dataclasses.
            guarded: A model whose validator changes its input in place.
            guarded_data: A dataclass whose `__post_init__` changes its input
                in place.
            counted: A dataclass with a default factory.
            pydantic_counted: A Pydantic dataclass with a default factory.
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
                    aliased=aliased,
                    split_alias=split_alias,
                    unserializable=unserializable,
                    doubled=doubled,
                    normalized=normalized,
                    outer=outer,
                    holder=holder,
                    wrapper=wrapper,
                    outers=outers,
                    guarded=guarded,
                    guarded_data=guarded_data,
                    counted=counted,
                    pydantic_counted=pydantic_counted,
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
        ({"doubled": {"x": 3}}, {"doubled": {"x": 6}}),
        ({"normalized": {"name": "ABC"}}, {"normalized": {"name": "abc", "size": 7}}),
    ],
    ids=[
        "model",
        "list-of-models",
        "model-or-dict",
        "validator",
        "flag-validator",
        "dataclass-validator",
        "dataclass-post-init",
    ],
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
        # serializes as {"out_value": ...}, which the tool's schema rejects
        (
            {"split_alias": {"in_value": "x"}},
            {"split_alias": {"out_value": "x"}},
        ),
    ],
    ids=["mapping", "nested-lazy", "split-alias"],
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
    assert "cannot be shown to approvers or monitors" in message.error.message
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
        ({"bumped": {"n": 2}}, None),
        ({"doubled": {"x": 6}}, None),
        ({"normalized": {"name": "ABC"}}, None),
        # values that serialize as selected run
        (
            {"step": {"step": "act", "status": "pending"}},
            {"step": {"step": "act", "status": "pending"}},
        ),
        (
            {"normalized": {"name": "abc", "size": 1}},
            {"normalized": {"name": "abc", "size": 1}},
        ),
        # so do ones that leave out fields their defaults fill in
        ({"step": {"step": "act"}}, {"step": {"step": "act", "status": "pending"}}),
        ({"normalized": {"name": "abc"}}, {"normalized": {"name": "abc", "size": 7}}),
        # nested: defaults may be left out, supplied values must not change
        (
            {"outer": {"inner": {"name": "abc"}}},
            {"outer": {"inner": {"name": "abc", "size": 7}}},
        ),
        ({"outer": {"inner": {"name": "ABC"}}}, None),
        (
            {"holder": {"inner": {"name": "abc"}}},
            {"holder": {"inner": {"name": "abc", "size": 7}}},
        ),
        (
            {"wrapper": {"step": {"step": "act"}}},
            {"wrapper": {"step": {"step": "act", "status": "pending"}}},
        ),
        (
            {"outers": [{"inner": {"name": "abc"}}]},
            {"outers": [{"inner": {"name": "abc", "size": 7}}]},
        ),
    ],
    ids=[
        "validator-changes-it",
        "dataclass-validator-changes-it",
        "post-init-changes-it",
        "serializes-as-selected",
        "dataclass-serializes-as-selected",
        "model-default-left-out",
        "dataclass-default-left-out",
        "dataclass-in-dataclass-default-left-out",
        "nested-post-init-changes-it",
        "dataclass-in-model-default-left-out",
        "model-in-dataclass-default-left-out",
        "list-of-nested-default-left-out",
    ],
)
async def test_modified_value_runs_only_as_selected(
    modified: dict[str, Any], runs: dict[str, Any] | None
) -> None:
    received: list[Any] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments=modified),
        [model_tool(received)],
        [ApprovalPolicy(modifying_approver(modified), "*")],
    )

    if runs is not None:
        assert message.error is None
        assert json_equal(to_jsonable_python(received), [runs])
    else:
        assert message.error is not None
        assert message.error.type == "approval"
        assert received == []


@pytest.mark.parametrize("name", ["guarded", "guarded_data"])
async def test_constructor_cannot_change_the_selected_call(name: str) -> None:
    """A constructor that changes its input in place changes a copy."""
    selected = ToolCall(
        id="1", function="model_tool", arguments={name: {"flags": {"write": False}}}
    )

    @approver
    def selecting_approver() -> Approver:
        async def approve(
            message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
        ) -> Approval:
            return Approval(decision="modify", modified=selected)

        return approve

    received: list[Any] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments={name: {"flags": {}}}),
        [model_tool(received)],
        [ApprovalPolicy(selecting_approver(), "*")],
    )

    assert message.error is not None
    assert message.error.type == "approval"
    assert received == []
    assert selected.arguments == {name: {"flags": {"write": False}}}


@pytest.mark.parametrize("name", ["counted", "pydantic_counted"])
async def test_modify_leaving_out_a_default_factory_field_runs(name: str) -> None:
    """The comparison does not call a default factory again."""
    received: list[Any] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments={name: {"name": "a"}}),
        [model_tool(received)],
        [ApprovalPolicy(modifying_approver({name: {"name": "b"}}), "*")],
    )

    assert message.error is None
    (values,) = received
    assert values[name].name == "b"


async def test_aliased_model_is_shown_as_its_schema_reads() -> None:
    """A model is shown by alias without computed fields, so a modify that copies it runs."""
    received: list[Any] = []
    calls: list[ToolCall] = []
    arguments = {"aliased": {"filePath": "a/b.txt"}, "step": {"step": "plan"}}
    message = await execute_with_approval(
        ToolCall(id="1", function="model_tool", arguments=arguments),
        [model_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )
    assert message.error is None
    (call,) = calls
    assert call.arguments == {
        "aliased": {"filePath": "a/b.txt"},
        "step": {"step": "plan", "status": "pending"},
    }

    # the shown call, with another argument changed
    modified = {**call.arguments, "step": {"step": "act", "status": "pending"}}
    message = await execute_with_approval(
        ToolCall(id="2", function="model_tool", arguments=arguments),
        [model_tool(received)],
        [ApprovalPolicy(modifying_approver(modified), "*")],
    )
    assert message.error is None
    assert received[-1]["aliased"].file_path == "a/b.txt"
    assert received[-1]["step"] == Step(step="act")


async def test_model_serializer_failure() -> None:
    """A model that cannot be serialized is a parsing error only when it must be shown."""
    received: list[Any] = []
    calls: list[ToolCall] = []
    call = ToolCall(
        id="1", function="model_tool", arguments={"unserializable": {"value": "x"}}
    )
    message = await execute_with_approval(
        call,
        [model_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )
    assert message.error is not None
    assert message.error.type == "parsing"
    assert "serializing it failed" in message.error.message
    assert calls == []
    assert received == []

    # without approval the model is not serialized and the tool runs
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])], [model_tool(received)]
    )
    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is None
    assert received == [{"unserializable": Unserializable(value="x")}]


@agent
def amount_agent(received: list[dict[str, Any]]) -> Agent:
    async def execute(
        state: AgentState, amount: float, note: str = "", tags: list[str] | None = None
    ) -> AgentState:
        """Record an amount.

        Args:
            state: Agent state.
            amount: An amount.
            note: A note.
            tags: Tags.
        """
        received.append({"amount": amount, "note": note, "tags": tags})
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
        assert received == [{"amount": 5.0, "note": "curried", "tags": None}]
        assert isinstance(received[0]["amount"], float)
    else:
        assert message.error is not None
        assert message.error.type == "parsing"
        assert calls == []
        assert received == []


async def test_curried_handoff_arguments_are_passed_as_given() -> None:
    """Curried arguments come from the developer, so they are not converted."""
    from inspect_ai.agent import handoff

    received: list[dict[str, Any]] = []
    note, tags = Path("notes.txt"), {"a"}
    call = ToolCall(
        id="1", function="transfer_to_amount_agent", arguments={"amount": 5}
    )
    messages, _ = await execute_tools(
        [
            ChatMessageUser(content="go"),
            ChatMessageAssistant(content="", tool_calls=[call]),
        ],
        [handoff(amount_agent(received), note=note, tags=tags)],
        approval=[ApprovalPolicy(recording_approver([]), "*")],
    )
    (message,) = [m for m in messages if isinstance(m, ChatMessageTool)]

    assert message.error is None
    (values,) = received
    assert values["note"] is note
    assert values["tags"] is tags


def test_modify_arguments_run_and_are_recorded() -> None:
    """The modified arguments run; the log keeps the model's proposal beside them."""
    policy = ApprovalPolicy(approver=modifying_approver({"x": 2, "y": 3}), tools="*")
    log = eval_with_approval(policy).log

    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]

    # the model's proposal is recorded as it was made
    model_event = next(e for e in sample.events if isinstance(e, ModelEvent))
    assert model_event.output.message.tool_calls
    proposed = model_event.output.message.tool_calls[0]
    assert proposed.arguments == {"x": 1, "y": 1}
    approval_event = find_approval(log)
    assert approval_event and approval_event.decision == "modify"
    assert approval_event.call.arguments == {"x": 1, "y": 1}
    assert approval_event.modified
    assert approval_event.modified.arguments == {"x": 2, "y": 3}

    # the tool event and tool message show what ran
    (tool_event,) = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert (tool_event.function, tool_event.arguments) == ("addition", {"x": 2, "y": 3})
    (tool_message,) = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert tool_message.text == "5"


def test_modify_to_another_function_fails_the_sample() -> None:
    """A `modify` may not change the function: the sample fails and nothing runs."""
    calls: list[str] = []
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition(), echo(calls)), generate()],
        scorer=match(numeric=True),
    )
    policy = ApprovalPolicy(
        approver=modifying_approver({"text": "2"}, function="echo"), tools="addition"
    )
    log = eval(task, model=approval_model(), approval=[policy])[0]

    assert log.status == "error"
    assert log.samples
    sample = log.samples[0]
    assert sample.error is not None
    assert "modified call to 'echo' for a call to 'addition'" in sample.error.message
    assert "may change only the arguments" in sample.error.message
    assert calls == []
    (tool_event,) = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert tool_event.function == "addition"
    assert tool_event.failed is True
    assert not any(isinstance(m, ChatMessageTool) for m in sample.messages)


async def test_execute_tools_modify_to_another_function_runs_neither_tool() -> None:
    import pytest

    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_def import ToolDef

    proposed_calls: list[str] = []
    target_calls: list[str] = []
    target = ToolDef(echo(target_calls), name="target")
    call = ToolCall(id="test", function="echo", arguments={"text": "proposed"})

    with pytest.raises(RuntimeError, match="may change only the arguments"):
        await execute_tools(
            [ChatMessageAssistant(content=[], tool_calls=[call])],
            [ToolDef(echo(proposed_calls)), target],
            approval=[
                ApprovalPolicy(
                    approver=modifying_approver({"text": "target"}, function="target"),
                    tools="*",
                )
            ],
        )

    assert proposed_calls == []
    assert target_calls == []


def test_modify_without_a_modified_call_rejects_the_call() -> None:
    """A `modify` that carries no modified call must not run the original."""
    policy = ApprovalPolicy(approver=auto_approver("modify"), tools="*")
    log = eval_with_approval(policy).log

    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    # the approval event keeps the decision the approver returned
    approval_event = find_approval(log)
    assert approval_event and approval_event.decision == "modify"
    assert approval_event.modified is None
    # the call was rejected, with an explanation the model can act on
    (tool_event,) = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert tool_event.error is not None
    assert tool_event.error.type == "approval"
    (tool_message,) = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert tool_message.error is not None
    assert tool_message.error.type == "approval"
    assert "no modified call" in tool_message.error.message
    assert "not run" in tool_message.error.message


async def test_execute_tools_modify_without_a_modified_call_runs_nothing() -> None:
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_def import ToolDef

    calls: list[str] = []
    call = ToolCall(id="test", function="echo", arguments={"text": "proposed"})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [ToolDef(echo(calls))],
        approval=[ApprovalPolicy(approver=auto_approver("modify"), tools="*")],
    )

    assert calls == []
    assert isinstance(messages[-1], ChatMessageTool)
    assert messages[-1].error is not None
    assert messages[-1].error.type == "approval"


@pytest.mark.parametrize("surface", ["panel", "console"])
async def test_human_approver_drops_modify_from_choices(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    surface: str,
) -> None:
    """A human can't supply a modified call, so Modify is never presented."""
    from inspect_ai.approval._human import acp as acp_module
    from inspect_ai.approval._human import approver as approver_module
    from inspect_ai.approval._human.approver import human_approver

    presented: list[list[ApprovalDecision]] = []

    async def no_acp(**kwargs: object) -> Approval | None:
        return None

    async def panel(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
        choices: list[ApprovalDecision],
    ) -> Approval:
        if surface == "console":
            raise NotImplementedError
        presented.append(choices)
        return Approval(decision="approve")

    def console(
        message: str,
        view: ToolCallView,
        choices: list[ApprovalDecision],
        arguments: object,
    ) -> Approval:
        presented.append(choices)
        return Approval(decision="approve")

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", no_acp)
    monkeypatch.setattr(approver_module, "panel_approval", panel)
    monkeypatch.setattr(approver_module, "console_approval", console)

    with caplog.at_level(logging.WARNING):
        approve = human_approver(["approve", "modify", "reject"])
    assert "'modify' choice" in caplog.text

    call = ToolCall(id="t1", function="bash", arguments={"cmd": "ls"})
    await approve("run it?", call, ToolCallView(), [])

    assert presented == [["approve", "reject"]]


def test_human_approver_rejects_modify_as_the_only_choice() -> None:
    from inspect_ai.approval._human.approver import human_approver

    with pytest.raises(ValueError, match="does not support the 'modify' choice"):
        human_approver(["modify"])


if __name__ == "__main__":
    test_approve_escalate()
