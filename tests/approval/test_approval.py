import fnmatch
import json
import logging
import math
import ntpath
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, NamedTuple

import pytest
from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
    SecretStr,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticSerializationError

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai._util.json import to_json_str_safe
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
    config_from_approval_policies,
    policy_approver,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log import read_eval_log
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools, parse_tool_call
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
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


# --- approval decides on the call that will run ------------------------------
# (design/tool-approval-arguments.md)


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
    call: ToolCall, tools: list[Any], policies: list[ApprovalPolicy] | None
) -> ChatMessageTool:
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        tools,
        approval=policies,
    )
    assert isinstance(messages[-1], ChatMessageTool)
    return messages[-1]


def logged_tool_event() -> ToolEvent:
    (event,) = [e for e in transcript().events if isinstance(e, ToolEvent)]
    return ToolEvent.model_validate_json(event.model_dump_json())


def logged_approval_events() -> list[ApprovalEvent]:
    return [
        ApprovalEvent.model_validate_json(e.model_dump_json())
        for e in transcript().events
        if isinstance(e, ApprovalEvent)
    ]


def json_viewer(viewed: list[dict[str, Any]]) -> Any:
    def viewer(call: ToolCall) -> ToolCallView:
        viewed.append(call.arguments)
        content = json.dumps(call.arguments, sort_keys=True)
        return ToolCallView(call=ToolCallContent(format="text", content=content))

    return viewer


class Step(BaseModel):
    name: str
    status: Literal["pending", "done"] = "pending"

    @field_validator("name")
    @classmethod
    def lowercase(cls, name: str) -> str:
        return name.lower()


@dataclass
class Label:
    text: str

    def __post_init__(self) -> None:
        self.text = self.text.strip()


class Doubled(BaseModel):
    n: int

    @field_validator("n")
    @classmethod
    def double(cls, n: int) -> int:
        return n * 2


class Lazy(BaseModel):
    values: Iterable[int]


class SplitAlias(BaseModel):
    value: int = Field(validation_alias="in", serialization_alias="out")


class Unserializable(BaseModel):
    value: str

    @field_serializer("value")
    def fail(self, value: str) -> str:
        raise ValueError("cannot serialize")


class Rounded(BaseModel):
    amount: float

    @field_serializer("amount")
    def round_amount(self, amount: float) -> float:
        return round(amount, 2)


class Secret(BaseModel):
    key: SecretStr


class Privileged(BaseModel):
    command: str
    sudo: bool = Field(False, exclude=True)


_tokens = iter(range(1_000_000))


class Tokened(BaseModel):
    name: str
    token: int = Field(default_factory=lambda: next(_tokens))


class Capped(BaseModel):
    """A number the validator turns into infinity beyond 100 either way."""

    x: float

    @field_validator("x")
    @classmethod
    def cap(cls, x: float) -> float:
        return math.copysign(math.inf, x) if abs(x) > 100 else x


class Unpaired(BaseModel):
    """Text whose validator turns `<hi>` into an unpaired surrogate."""

    text: str

    @field_validator("text")
    @classmethod
    def unpair(cls, text: str) -> str:
        return text.replace("<hi>", "\ud800")


class Digits(BaseModel):
    """A number of digits the validator turns into a number that long."""

    n: int = Field(repr=False)

    @field_validator("n")
    @classmethod
    def lengthen(cls, n: int) -> int:
        return 10 ** (n - 1) if 1 < n <= 5000 else n


def nested_lists(depth: int) -> list[Any]:
    """Lists nested `depth` levels deep."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


class Nested(BaseModel):
    """A number the validator turns into lists nested that deep."""

    value: Any

    @field_validator("value")
    @classmethod
    def nest(cls, value: Any) -> Any:
        return nested_lists(value) if isinstance(value, int) else value


class Incomparable:
    """A value whose equality raises."""

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("compared")

    __hash__ = object.__hash__


class Guarded(BaseModel):
    name: str
    _guard: Incomparable = PrivateAttr(default_factory=Incomparable)


class Named(BaseModel):
    file_name: str = Field(alias="fileName")

    @computed_field
    def stem(self) -> str:
        return self.file_name.split(".")[0]


class Consuming(BaseModel):
    values: list[int]

    @model_validator(mode="before")
    @classmethod
    def consume(cls, data: Any) -> Any:
        data["values"].append(0)
        return data


@tool
def step_tool(received: list[dict[str, Any]]) -> Tool:
    async def execute(
        step: Step | None = None,
        steps: dict[str, Step] | None = None,
        label: Label | None = None,
        when: date | None = None,
        doubled: Doubled | None = None,
        lazy: Lazy | None = None,
        split: SplitAlias | None = None,
        unserializable: Unserializable | None = None,
        named: Named | None = None,
        consuming: Consuming | None = None,
        secret: Secret | None = None,
        privileged: Privileged | None = None,
        tokened: Tokened | None = None,
        guarded: Guarded | None = None,
        capped: Capped | None = None,
        rounded: Rounded | None = None,
        unpaired: Unpaired | None = None,
        digits: Digits | None = None,
        nested: Nested | None = None,
    ) -> str:
        """Record its arguments.

        Args:
            step: A step.
            steps: Steps by name.
            label: A label.
            when: A date.
            doubled: A number the validator doubles.
            lazy: A lazy iterable.
            split: A model with different validation and serialization aliases.
            unserializable: A model whose serializer fails.
            named: A model with an alias and a computed field.
            consuming: A model whose validator changes its input in place.
            secret: A model with a secret, which serializes masked.
            privileged: A model with a field left out of serialization.
            tokened: A model with a generated default.
            guarded: A model with a private attribute whose equality raises.
            capped: A model whose validator turns large numbers into infinity.
            rounded: A model whose serializer rounds.
            unpaired: A model whose validator can produce an unpaired surrogate.
            digits: A model whose validator can produce a very long integer.
            nested: A model whose validator can produce deeply nested lists.
        """
        arguments = {
            "step": step,
            "steps": steps,
            "label": label,
            "when": when,
            "doubled": doubled,
            "lazy": list(lazy.values) if lazy is not None else None,
            "split": split,
            "unserializable": unserializable,
            "named": named,
            "consuming": consuming,
            "secret": secret,
            "privileged": privileged,
            "tokened": tokened,
            "guarded": guarded,
            "capped": capped,
            "rounded": rounded,
            "unpaired": unpaired,
            "digits": digits,
            "nested": nested,
        }
        received.append({k: v for k, v in arguments.items() if v is not None})
        return "done"

    return execute


@pytest.mark.parametrize(
    "function,arguments",
    [
        ("addition", {"x": "one", "y": 1}),
        ("step_tool", {"when": "not-a-date"}),
    ],
    ids=["fails-schema", "fails-conversion"],
)
async def test_invalid_call_never_reaches_approver(
    function: str, arguments: dict[str, Any]
) -> None:
    viewed: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function=function, arguments=arguments),
        [
            ToolDef(addition(), viewer=json_viewer(viewed)),
            ToolDef(step_tool(received), viewer=json_viewer(viewed)),
        ],
        [ApprovalPolicy(recording_approver(calls, "reject"), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert calls == []
    assert viewed == []


async def test_approver_sees_the_arguments_as_converted() -> None:
    """The approver, the viewer and the log see what the tool gets, defaults included."""
    init_transcript(Transcript())
    viewed: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(
            id="1",
            function="step_tool",
            arguments={
                "step": {"name": "WRITE"},
                "steps": {"b": {"name": "B", "status": "done"}},
                "label": {"text": " tests "},
                "when": "2026-10-15",
            },
        ),
        [ToolDef(step_tool(received), viewer=json_viewer(viewed))],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    shown = {
        "step": {"name": "write", "status": "pending"},
        "steps": {"b": {"name": "b", "status": "done"}},
        "label": {"text": "tests"},
        "when": "2026-10-15",
    }
    assert message.error is None
    assert [call.arguments for call in calls] == [shown]
    assert viewed and all(arguments == shown for arguments in viewed)
    assert received == [
        {
            "step": Step(name="write"),
            "steps": {"b": Step(name="b", status="done")},
            "label": Label("tests"),
            "when": date(2026, 10, 15),
        }
    ]
    event = logged_tool_event()
    assert event.arguments == shown
    assert event.view is not None
    assert event.view.content == json.dumps(shown, sort_keys=True)


@pytest.mark.parametrize(
    "arguments",
    [
        {"doubled": {"n": 2}},
        {"split": {"in": 1}},
        {"unserializable": {"value": "x"}},
        {"secret": {"key": "k"}},
        {"privileged": {"command": "ls", "sudo": True}},
        {"lazy": {"values": [1, 2, 3]}},
        {"rounded": {"amount": 1.234}},
    ],
    ids=[
        "validator-not-idempotent",
        "mismatched-alias",
        "serializer-fails",
        "masked-secret",
        "excluded-field",
        "lazy-iterable",
        "rounding-serializer",
    ],
)
async def test_arguments_that_do_not_rebuild_are_refused(
    arguments: dict[str, Any],
) -> None:
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments=arguments),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert "cannot be shown to approvers or monitors" in message.error.message
    assert calls == []
    assert received == []


async def test_a_value_that_cannot_be_compared_is_refused() -> None:
    """An argument whose equality raises is a parsing error, not a failed sample."""
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments={"guarded": {"name": "a"}}),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert "Argument 'guarded' cannot be shown" in message.error.message
    assert calls == []
    assert received == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"capped": {"x": 101}},
        {"capped": {"x": -101}},
        {"unpaired": {"text": "a<hi>"}},
        {"digits": {"n": 4301}},
    ],
    ids=["infinity", "negative-infinity", "unpaired-surrogate", "unreadable-integer"],
)
async def test_a_shown_value_the_log_cannot_store_is_refused(
    arguments: dict[str, Any],
) -> None:
    """A converted value the event writer would change is refused before approval."""
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments=arguments),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    (name,) = arguments
    assert message.error is not None
    assert message.error.type == "parsing"
    assert f"Argument '{name}' cannot be shown" in message.error.message
    assert "the log cannot store unchanged" in message.error.message
    assert calls == []
    assert received == []


@pytest.mark.parametrize(
    "arguments,shown",
    [
        ({"capped": {"x": 1}}, {"capped": {"x": 1.0}}),
        ({"unpaired": {"text": "é 😀"}}, {"unpaired": {"text": "é 😀"}}),
        ({"unpaired": {"text": "\\ud800"}}, {"unpaired": {"text": "\\ud800"}}),
        ({"digits": {"n": 4300}}, {"digits": {"n": 10**4299}}),
    ],
    ids=["finite", "unicode", "backslash-u-text", "longest-readable-integer"],
)
async def test_the_persisted_events_keep_the_shown_arguments(
    arguments: dict[str, Any], shown: dict[str, Any]
) -> None:
    """The ApprovalEvent and ToolEvent as the log writes them reload with the shown call."""
    init_transcript(Transcript())
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments=arguments),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is None
    assert [call.arguments for call in calls] == [shown]
    [approval] = [e for e in transcript().events if isinstance(e, ApprovalEvent)]
    persisted = ApprovalEvent.model_validate_json(to_json_str_safe(approval))
    assert persisted.call.arguments == shown
    [tool_event] = [e for e in transcript().events if isinstance(e, ToolEvent)]
    assert (
        ToolEvent.model_validate_json(to_json_str_safe(tool_event)).arguments == shown
    )


@pytest.mark.parametrize(
    "depth,oversight,refused",
    [(98, True, False), (99, True, True), (251, True, True), (251, False, False)],
    ids=["at-limit", "over-limit", "unwritable", "unwritable-without-oversight"],
)
async def test_converted_nesting_is_bounded_under_oversight(
    depth: int, oversight: bool, refused: bool
) -> None:
    """Converted arguments get the same nesting bound as the model's arguments."""
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments={"nested": {"value": depth}}),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")] if oversight else None,
    )

    if refused:
        assert message.error is not None
        assert message.error.type == "parsing"
        assert "Argument 'nested' cannot be shown" in message.error.message
        assert "maximum supported nesting depth of 100" in message.error.message
        assert calls == []
        assert received == []
    else:
        assert message.error is None
        assert received == [{"nested": Nested(value=nested_lists(depth))}]


def test_converted_nesting_at_the_limit_is_written_and_read_back(
    tmp_path: Path,
) -> None:
    """The deepest accepted converted call is in the log as shown and ran."""
    shown = {"nested": {"value": nested_lists(98)}}
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="step_tool",
                tool_arguments={"nested": {"value": 98}},
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="go")], solver=[use_tools(step_tool([])), generate()]
    )
    [log] = eval(
        task,
        model=model,
        approval=[ApprovalPolicy(auto_approver(), "*")],
        log_dir=str(tmp_path),
    )
    assert log.status == "success", log.error

    log = read_eval_log(log.location)
    assert log.samples
    events = log.samples[0].events
    [approval] = [e for e in events if isinstance(e, ApprovalEvent)]
    assert approval.call.arguments == shown
    [tool_event] = [e for e in events if isinstance(e, ToolEvent)]
    assert tool_event.arguments == shown
    assert tool_event.error is None


async def test_a_generated_default_runs_as_shown() -> None:
    """A default generated when the model is built is shown and runs unchanged."""
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments={"tokened": {"name": "a"}}),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    assert message.error is None
    [shown] = [call.arguments for call in calls]
    token = shown["tokened"]["token"]
    assert received == [{"tokened": Tokened(name="a", token=token)}]


@pytest.mark.parametrize(
    "modified,error",
    [
        ({"step": {"name": "test", "status": "done"}}, None),
        ({"step": {"name": "test"}}, "approval"),
        ({"step": {"name": "TEST", "status": "done"}}, "approval"),
        ({"step": {"name": 5, "status": "done"}}, "parsing"),
    ],
    ids=["full", "omits-default", "validator-changes-it", "invalid"],
)
async def test_modify_runs_only_as_selected(
    modified: dict[str, Any], error: str | None
) -> None:
    init_transcript(Transcript())
    viewed: list[dict[str, Any]] = []
    received: list[dict[str, Any]] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments={"step": {"name": "write"}}),
        [ToolDef(step_tool(received), viewer=json_viewer(viewed))],
        [ApprovalPolicy(modifying_approver(modified), "*")],
    )

    # the event records the modified call, whether or not it ran
    event = logged_tool_event()
    assert event.arguments == modified
    if error is None:
        assert message.error is None
        assert received == [{"step": Step(name="test", status="done")}]
        assert event.view is not None
        assert event.view.content == json.dumps(modified, sort_keys=True)
    else:
        assert message.error is not None
        assert message.error.type == error
        assert event.error is not None
        assert event.error.type == error
        assert received == []


async def test_a_model_is_shown_by_alias_without_computed_fields() -> None:
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    shown = {"named": {"fileName": "a.txt"}}
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments=deepcopy(shown)),
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )
    assert message.error is None
    assert [call.arguments for call in calls] == [shown]

    selected: dict[str, object] = {"named": {"fileName": "b.txt"}}
    message = await execute_with_approval(
        ToolCall(id="2", function="step_tool", arguments=deepcopy(shown)),
        [step_tool(received)],
        [ApprovalPolicy(modifying_approver(deepcopy(selected)), "*")],
    )
    assert message.error is None
    assert [r["named"].file_name for r in received] == ["a.txt", "b.txt"]


@pytest.mark.parametrize("oversight", [True, False], ids=["approval", "no-approval"])
async def test_a_constructor_cannot_change_the_call(oversight: bool) -> None:
    """Conversion gets a copy, so a validator that changes its input leaves the call."""
    init_transcript(Transcript())
    calls: list[ToolCall] = []
    received: list[dict[str, Any]] = []
    arguments = {"consuming": {"values": [1]}}
    call = ToolCall(id="1", function="step_tool", arguments=deepcopy(arguments))
    message = await execute_with_approval(
        call,
        [step_tool(received)],
        [ApprovalPolicy(recording_approver(calls), "*")] if oversight else None,
    )

    assert call.arguments == arguments
    if oversight:
        # the shown value [1, 0] would rebuild as [1, 0, 0]
        assert message.error is not None and message.error.type == "parsing"
        assert calls == [] and received == []
    else:
        assert message.error is None
        assert [r["consuming"].values for r in received] == [[1, 0]]
        assert logged_tool_event().arguments == arguments


def mutating_viewer(call: ToolCall) -> ToolCallView:
    call.arguments["step"]["name"] = "changed"
    return ToolCallView()


async def test_a_viewer_cannot_change_the_call_that_runs() -> None:
    """The viewer for the logged view gets a copy of the call that runs."""
    init_transcript(Transcript())
    received: list[dict[str, Any]] = []
    modified: dict[str, object] = {"step": {"name": "test", "status": "done"}}
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments={"step": {"name": "write"}}),
        [ToolDef(step_tool(received), viewer=mutating_viewer)],
        [ApprovalPolicy(modifying_approver(deepcopy(modified)), "*")],
    )

    assert message.error is None
    assert received == [{"step": Step(name="test", status="done")}]
    assert logged_tool_event().arguments == modified


async def test_the_call_shown_has_a_view_of_its_converted_arguments() -> None:
    """The prepared call's view is rendered from what the approver sees."""
    viewed: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
    viewer = json_viewer(viewed)
    raw: dict[str, Any] = {"step": {"name": "WRITE"}}
    call = ToolCall(id="1", function="step_tool", arguments=raw)
    call.view = viewer(deepcopy(call)).call
    message = await execute_with_approval(
        call,
        [ToolDef(step_tool([]), viewer=viewer)],
        [ApprovalPolicy(recording_approver(calls), "*")],
    )

    shown = {"step": {"name": "write", "status": "pending"}}
    assert message.error is None
    (approved,) = calls
    assert approved.arguments == shown
    assert approved.view is not None
    assert approved.view.content == json.dumps(shown, sort_keys=True)
    assert call.view is not None
    assert call.view.content == json.dumps(raw, sort_keys=True)


@approver
def in_place_approver(
    edit: Literal["arguments", "function", "id"], decision: ApprovalDecision
) -> Approver:
    """Approver which changes the call in place."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        if edit == "arguments":
            call.arguments["x"] = 5
        elif edit == "function":
            call.function = "other"
        else:
            call.id = "renamed"
        if decision == "modify":
            arguments = {"x": 7, "y": 1}
            return Approval(
                decision="modify",
                modified=ToolCall(
                    id=call.id, function=call.function, arguments=arguments
                ),
            )
        return Approval(decision=decision)

    return approve


@pytest.mark.parametrize(
    "edit,decision",
    [
        ("arguments", "escalate"),
        ("arguments", "approve"),
        ("function", "approve"),
        ("id", "approve"),
    ],
)
async def test_an_approver_cannot_change_the_call_in_place(
    edit: Literal["arguments", "function", "id"], decision: ApprovalDecision
) -> None:
    """An in-place edit is refused: an approver changes a call with `modify`."""
    init_transcript(Transcript())
    seen: list[ToolCall] = []
    message = await execute_with_approval(
        ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1}),
        [addition()],
        [
            ApprovalPolicy(in_place_approver(edit, decision), "*"),
            ApprovalPolicy(recording_approver(seen), "*"),
        ],
    )

    assert message.error is not None
    assert message.error.type == "approval"
    assert "changed the tool call in place" in message.error.message
    assert message.text == ""
    assert len(seen) == (1 if decision == "escalate" else 0)
    event = logged_tool_event()
    assert event.error is not None and event.error.type == "approval"
    # each approval event keeps the call as presented to its approver
    presented = ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1})
    approvals = logged_approval_events()
    assert approvals[0].call == presented
    assert approvals[0].decision == decision
    if decision == "escalate":
        assert approvals[1].call.arguments == {"x": 5, "y": 1}


@approver
def copying_approver() -> Approver:
    """Approver which modifies a copy of the call it is given."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        arguments = deepcopy(call.arguments)
        arguments["x"] = 5
        return Approval(
            decision="modify",
            modified=ToolCall(id=call.id, function=call.function, arguments=arguments),
        )

    return approve


@pytest.mark.parametrize(
    "policy,result",
    [(copying_approver(), "6"), (in_place_approver("arguments", "modify"), "8")],
    ids=["copy", "in-place"],
)
async def test_an_approver_changes_a_call_with_modify(
    policy: Approver, result: str
) -> None:
    """A modify runs as selected, whatever happened to the call it was given."""
    message = await execute_with_approval(
        ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1}),
        [addition()],
        [ApprovalPolicy(policy, "*")],
    )

    assert message.error is None
    assert message.text == result


@approver
def approving_with_modified_approver(edit: bool) -> Approver:
    """Approver which approves, with a `modified` call attached."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        if edit:
            call.arguments["x"] = 5
        modified = ToolCall(
            id=call.id, function=call.function, arguments={"x": 7, "y": 1}
        )
        return Approval(decision="approve", modified=modified)

    return approve


@pytest.mark.parametrize("edit", [False, True], ids=["unchanged", "in-place"])
async def test_an_approve_runs_the_call_as_shown(edit: bool) -> None:
    """An approve runs the call as shown, even with a `modified` call attached."""
    message = await execute_with_approval(
        ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1}),
        [addition()],
        [ApprovalPolicy(approving_with_modified_approver(edit), "*")],
    )

    if edit:
        assert message.error is not None and message.error.type == "approval"
        assert "changed the tool call in place" in message.error.message
        assert message.text == ""
    else:
        assert message.error is None
        assert message.text == "11"


@approver
def renaming_modify_approver(selected: str) -> Approver:
    """Approver which renames the call it is given, then returns a modify."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        call.function = "other"
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id, function=selected, arguments={"x": 7, "y": 1}
            ),
        )

    return approve


async def test_a_modify_keeps_the_function_as_shown() -> None:
    """A modify may select only the function shown, whatever the approver renamed."""
    init_transcript(Transcript())
    message = await execute_with_approval(
        ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1}),
        [addition()],
        [ApprovalPolicy(renaming_modify_approver("addition"), "*")],
    )
    assert message.error is None
    assert message.text == "8"
    [approval_event] = logged_approval_events()
    assert approval_event.call.function == "addition"

    with pytest.raises(RuntimeError, match="may change only the arguments"):
        await execute_with_approval(
            ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1}),
            [addition()],
            [ApprovalPolicy(renaming_modify_approver("other"), "*")],
        )


@approver
def reidentifying_approver() -> Approver:
    """Approver which returns a modify with another call id."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(
                id="other", function=call.function, arguments={"x": 7, "y": 1}
            ),
        )

    return approve


async def test_a_modify_keeps_the_id_as_shown() -> None:
    """A modify that changes the call's id fails the sample, and nothing runs."""
    init_transcript(Transcript())
    with pytest.raises(RuntimeError, match="not its id"):
        await execute_with_approval(
            ToolCall(id="1", function="addition", arguments={"x": 10, "y": 1}),
            [addition()],
            [ApprovalPolicy(reidentifying_approver(), "*")],
        )
    event = logged_tool_event()
    assert event.id == "1"
    assert event.result == ""


@dataclass
class NonNegative:
    n: int

    def __post_init__(self) -> None:
        assert self.n >= 0


@tool
def non_negative_tool(received: list[int]) -> Tool:
    async def execute(value: NonNegative) -> str:
        """Record a value.

        Args:
            value: A value whose constructor asserts it is not negative.
        """
        received.append(value.n)
        return "done"

    return execute


@pytest.mark.parametrize(
    "policy",
    [None, "approve", "modify"],
)
async def test_a_failing_constructor_is_a_parsing_error(policy: str | None) -> None:
    """Any exception from building an argument (here an assert) goes back to the model."""
    init_transcript(Transcript())
    received: list[int] = []
    arguments = {"value": {"n": 1 if policy == "modify" else -1}}
    policies = {
        None: None,
        "approve": [ApprovalPolicy(recording_approver([]), "*")],
        "modify": [ApprovalPolicy(modifying_approver({"value": {"n": -1}}), "*")],
    }[policy]
    message = await execute_with_approval(
        ToolCall(id="1", function="non_negative_tool", arguments=arguments),
        [non_negative_tool(received)],
        policies,
    )

    assert message.error is not None
    assert message.error.type == "parsing"
    assert "Unable to convert argument 'value'" in message.error.message
    assert received == []
    event = logged_tool_event()
    assert event.arguments == {"value": {"n": -1}}
    assert event.error is not None and event.error.type == "parsing"


async def test_without_oversight_hidden_values_run() -> None:
    """Values that are refused under oversight run without it."""
    received: list[dict[str, Any]] = []
    arguments = {
        "secret": {"key": "k"},
        "privileged": {"command": "ls", "sudo": True},
        "lazy": {"values": [1, 2, 3]},
        "rounded": {"amount": 1.234},
        "digits": {"n": 4301},
    }
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments=arguments),
        [step_tool(received)],
        None,
    )

    assert message.error is None
    [args] = received
    assert args["secret"].key.get_secret_value() == "k"
    assert args["privileged"].sudo is True
    assert args["lazy"] == [1, 2, 3]
    assert args["rounded"].amount == 1.234
    assert args["digits"].n == 10**4300


@tool
def nan_scale() -> Tool:
    async def execute(x: float) -> str:
        """Return a number.

        Args:
            x: The number.
        """
        return str(x)

    return execute


@tool
def nan_default() -> Tool:
    async def execute(x: int, marker: float = float("nan")) -> str:
        """Return a number and a marker.

        Args:
            x: The number.
            marker: A marker.
        """
        return f"{x} {marker}"

    return execute


async def test_an_omitted_default_is_not_compared() -> None:
    """An omitted parameter is not shown, so its default runs whatever its equality."""
    message = await execute_with_approval(
        ToolCall(id="1", function="nan_default", arguments={"x": 1}),
        [nan_default()],
        [ApprovalPolicy(auto_approver(), "*")],
    )
    assert message.error is None
    assert message.text == "1 nan"


async def test_without_oversight_a_nan_argument_runs() -> None:
    """Without approval or a sentinel, nothing is compared, so NaN runs as on main."""
    message = await execute_with_approval(
        ToolCall(id="1", function="nan_scale", arguments={"x": float("nan")}),
        [nan_scale()],
        None,
    )
    assert message.error is None
    assert message.text == "nan"


async def test_without_oversight_the_call_runs_as_given() -> None:
    """With no approval or sentinel, nothing is serialized or rebuilt."""
    init_transcript(Transcript())
    received: list[dict[str, Any]] = []
    arguments = {"step": {"name": "WRITE"}, "doubled": {"n": 2}}
    message = await execute_with_approval(
        ToolCall(id="1", function="step_tool", arguments=arguments),
        [step_tool(received)],
        None,
    )

    assert message.error is None
    assert received == [{"step": Step(name="write"), "doubled": Doubled(n=2)}]
    assert received[0]["doubled"].n == 4
    assert logged_tool_event().arguments == arguments


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


async def test_curried_handoff_arguments_are_passed_as_given() -> None:
    """Curried arguments come from the developer, so they are not converted."""
    from inspect_ai.agent import handoff

    received: list[dict[str, Any]] = []
    calls: list[ToolCall] = []
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
        approval=[ApprovalPolicy(recording_approver(calls), "*")],
    )
    (message,) = [m for m in messages if isinstance(m, ChatMessageTool)]

    assert message.error is None
    assert [call.arguments for call in calls] == [{"amount": 5.0}]
    (values,) = received
    assert values["note"] is note
    assert values["tags"] is tags


class Unprintable:
    """A developer object that fails if it is formatted or compared."""

    def __str__(self) -> str:
        raise AssertionError("a developer value was formatted")

    __repr__ = __str__

    def __eq__(self, other: object) -> bool:
        raise AssertionError("a developer value was compared")

    __hash__ = object.__hash__


_HIDDEN_DEFAULT = Unprintable()


@agent
def hidden_default_agent(received: list[dict[str, Any]]) -> Agent:
    async def execute(
        state: AgentState, amount: float, note: Any = "", hidden: Any = _HIDDEN_DEFAULT
    ) -> AgentState:
        """Record an amount.

        Args:
            state: Agent state.
            amount: An amount.
            note: A note.
            hidden: A default the model does not set.
        """
        received.append({"amount": amount, "note": note, "hidden": hidden})
        return state

    return execute


@pytest.mark.parametrize(
    "policy",
    [None, "approve", "modify"],
    ids=["no-approval", "approval", "modify"],
)
async def test_curried_handoff_arguments_are_not_traced(policy: str | None) -> None:
    """Only the model's handoff arguments are formatted or compared."""
    from inspect_ai.agent import handoff

    received: list[dict[str, Any]] = []
    note = Unprintable()
    call = ToolCall(
        id="1", function="transfer_to_hidden_default_agent", arguments={"amount": 5}
    )
    policies = {
        None: None,
        "approve": [ApprovalPolicy(auto_approver(), "*")],
        "modify": [ApprovalPolicy(modifying_approver({"amount": 6}), "*")],
    }[policy]
    messages, _ = await execute_tools(
        [
            ChatMessageUser(content="go"),
            ChatMessageAssistant(content="", tool_calls=[call]),
        ],
        [handoff(hidden_default_agent(received), note=note)],
        approval=policies,
    )
    (message,) = [m for m in messages if isinstance(m, ChatMessageTool)]

    assert message.error is None
    (values,) = received
    assert values["amount"] == (6 if policy == "modify" else 5)
    assert values["note"] is note
    assert values["hidden"] is _HIDDEN_DEFAULT


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


async def routed(call: ToolCall, tools: str | list[str], **arguments: str) -> bool:
    """Whether a policy for `tools` and `arguments` decides on `call`."""
    policy = (
        ApprovalPolicy(auto_approver(), tools, arguments=arguments)
        if arguments
        else ApprovalPolicy(auto_approver(), tools)
    )
    approve = policy_approver([policy])
    approval = await approve("", call, ToolCallView(), [])
    return approval.decision == "approve"


def make_tool_call(function: str, **arguments: object) -> ToolCall:
    return ToolCall(id="1", function=function, arguments=arguments)


async def test_policy_name_glob_does_not_match_argument_text() -> None:
    assert await routed(make_tool_call("left_click"), "*_click")
    assert not await routed(make_tool_call("type", text="left_click"), "*_click")


@pytest.mark.parametrize(
    "tools,matched,unmatched",
    [
        ("computer", ["computer", "computer_use"], ["my_computer"]),
        ("*bash", ["bash", "my_bash"], ["bash_helper"]),
        ("foo*bar", ["foo_bar", "foobar"], ["foo_bar_baz"]),
        ("bash?", ["bash2"], ["bash", "bash22"]),
        ("bash[12]", ["bash1", "bash2"], ["bash3", "bash12"]),
    ],
)
async def test_policy_glob_names_are_not_prefix_matched(
    tools: str, matched: list[str], unmatched: list[str]
) -> None:
    for function in matched:
        assert await routed(make_tool_call(function), tools), function
    for function in unmatched:
        assert not await routed(make_tool_call(function), tools), function


async def test_policy_argument_value_cannot_supply_another_argument() -> None:
    call = make_tool_call("computer", action="type', mode='safe")
    assert not await routed(call, "computer(action='type'")
    assert not await routed(call, "computer", action="type", mode="safe")
    assert await routed(call, "computer", action="type', mode='safe")


async def test_policy_arguments_match_in_any_order() -> None:
    call = make_tool_call("computer", text="Return", action="key")
    assert await routed(call, "computer(action='key'")
    assert await routed(call, "computer", action="key")


async def test_policy_comma_list_of_names_with_arguments() -> None:
    for function in ("web_browser_type", "computer"):
        call = make_tool_call(function, action="key")
        assert await routed(call, "web_browser_type, computer", action="key")
    call = make_tool_call("computer", action="type")
    assert not await routed(call, "web_browser_type, computer", action="key")


async def test_policy_arguments_are_whole_value_globs() -> None:
    call = make_tool_call("bash", cmd="ls -la", timeout=10, sudo=True)
    assert await routed(call, "bash", cmd="ls*")
    assert not await routed(call, "bash", cmd="ls")
    assert not await routed(call, "bash", cmd="LS*")

    # other values are matched as their JSON
    assert await routed(call, "bash", timeout="1?", sudo="true")
    assert not await routed(call, "bash", timeout="1")

    # every listed argument must be present
    assert not await routed(call, "bash", cmd="ls*", user="*")


async def test_policy_arguments_match_parsed_non_json_values() -> None:
    # the parser's YAML fallback can produce dates and other non-JSON values
    tools = [
        ToolInfo(
            name="f",
            description="f",
            parameters=ToolParams(properties={"value": ToolParam(type="array")}),
        )
    ]
    call = parse_tool_call("1", "f", "- 2024-01-01\n- !!binary YQ==", tools)
    assert call.parse_error is None
    assert await routed(call, "f", value='*"2024-01-01", "a"*')
    assert not await routed(call, "f", value="2024*")

    # other types are not guessed at
    with pytest.raises(PydanticSerializationError):
        await routed(make_tool_call("f", value=object()), "f", value="*")


async def test_policy_arguments_match_json_values_pydantic_rejects() -> None:
    # JSON accepts a lone surrogate in an object key; Pydantic does not
    tools = [
        ToolInfo(
            name="f",
            description="f",
            parameters=ToolParams(properties={"value": ToolParam(type="object")}),
        )
    ]
    call = parse_tool_call("1", "f", '{"value": {"\\ud800": ["x"]}}', tools)
    assert call.parse_error is None
    assert await routed(call, "f", value="*")
    assert await routed(
        make_tool_call("f", value=[call.arguments["value"]]), "f", value="*"
    )


@pytest.mark.parametrize(
    "param_type,arguments",
    [
        ("object", '2024-01-01: blocked\n"2024-01-01": allowed'),
        ("object", 'outer:\n  2024-01-01: blocked\n  "2024-01-01": allowed'),
        ("array", '- 2024-01-01: blocked\n  "2024-01-01": allowed'),
        ("object", '!!binary YQ==: blocked\n"a": allowed'),
    ],
)
async def test_policy_arguments_refuse_parsed_key_collisions(
    param_type: Literal["object", "array"], arguments: str
) -> None:
    # the parser's YAML fallback can produce a key that converts to another key
    tools = [
        ToolInfo(
            name="f",
            description="f",
            parameters=ToolParams(properties={"value": ToolParam(type=param_type)}),
        )
    ]
    call = parse_tool_call("1", "f", arguments, tools)
    assert call.parse_error is None
    with pytest.raises(ValueError, match="two object keys"):
        await routed(call, "f", value="*allowed*")


async def test_policy_legacy_argument_form() -> None:
    patterns = ["computer(action='key'", "computer(action='left_click'"]
    assert await routed(make_tool_call("computer", action="key", text="a"), patterns)
    assert await routed(make_tool_call("computer", action="left_click"), patterns)

    # the value and the function are matched whole, as they were in the call text
    call = make_tool_call("computer", action="left_click_drag")
    assert not await routed(call, patterns)
    assert not await routed(make_tool_call("computer_use", action="key"), patterns)

    # `)` closes the argument list
    assert await routed(make_tool_call("bash", cmd="ls"), "bash(cmd='ls')")
    call = make_tool_call("bash", cmd="ls", timeout=10)
    assert not await routed(call, "bash(cmd='ls')")

    # the value is a glob
    assert await routed(make_tool_call("bash", cmd="rm -rf /"), "bash(cmd='rm *'")

    # names with `-` and `.` (bridged and MCP tools) are matched exactly
    pattern = "my-server.read_file(path='a.txt'"
    assert await routed(make_tool_call("my-server.read_file", path="a.txt"), pattern)
    assert not await routed(
        make_tool_call("my-server.read_files", path="a.txt"), pattern
    )

    # quoted values matched strings only
    for value in (10, True, ["key"], None):
        call = make_tool_call("computer", action=value)
        assert not await routed(call, "computer(action='*'")
    assert not await routed(make_tool_call("f", timeout=10), "f(timeout='10'")


async def test_policy_case_and_separator_rules_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # fnmatch ignores case through the platform's normcase; use Windows' here
    monkeypatch.setattr(fnmatch, "os", SimpleNamespace(path=ntpath))

    assert await routed(make_tool_call("computer", action="key"), "Computer")
    # except in the legacy form, open or closed
    assert not await routed(
        make_tool_call("computer", action="key"), "Computer(action='key'"
    )
    assert not await routed(
        make_tool_call("Computer", action="key"), "computer(action='key')"
    )
    call = make_tool_call("computer", action="KEY")
    assert not await routed(call, "computer", action="key")
    assert not await routed(call, "computer(action='key'")
    assert await routed(call, "computer(action='KEY'")

    # path separators in argument values are literal
    call = make_tool_call("read_file", path="C:\\data\\secret.txt")
    assert not await routed(call, "read_file(path='C:/data/*'")
    assert not await routed(call, "read_file", path="C:/data/*")


@pytest.mark.parametrize(
    "tools",
    [
        "bash(cmd='ls', timeout=10)",
        "computer(action='key', web_browser_type",
        "web_browser_type, computer(action='key'",
        "computer(*'key'*",
        'bash(cmd="ls"',
        "bash(cmd='it\\'s'",
        "bash(cmd='ls'), python",
        "computer*(action='key'",
        "computer*(action='key')",
        "comput?r(action='key'",
        "comput?r(action='key')",
        "[c]omputer(action='key'",
        "computer[s](action='key')",
    ],
)
def test_policy_refuses_other_argument_forms(tools: str) -> None:
    with pytest.raises(ValueError, match="'arguments'"):
        ApprovalPolicy(auto_approver(), tools)


def test_saved_policy_config_with_refused_pattern_raises() -> None:
    # a log's saved config still parses, but eval_retry() rebuilds the policies
    saved = {"approvers": [{"name": "auto", "tools": "bash(cmd='rm"}]}
    config = ApprovalPolicyConfig.model_validate(saved)
    assert config.approvers[0].arguments is None
    with pytest.raises(ValueError, match="'arguments'"):
        approval_policies_from_config(config)

    saved = {"approvers": [{"name": "auto", "tools": "computer(action='key'"}]}
    [policy] = approval_policies_from_config(ApprovalPolicyConfig.model_validate(saved))
    assert policy.arguments is None


def test_policy_refuses_legacy_form_with_arguments() -> None:
    with pytest.raises(ValueError, match="'arguments'"):
        ApprovalPolicy(auto_approver(), "computer(action='key'", {"text": "*"})


def test_policy_arguments_from_config(tmp_path: Path) -> None:
    config = tmp_path / "approval.yaml"
    config.write_text(
        "approvers:\n"
        "  - name: auto\n"
        "    tools: computer\n"
        "    arguments: {action: key}\n"
        "    decision: reject\n"
    )
    policies = read_approval_policies(config.as_posix())
    assert policies[0].arguments == {"action": "key"}

    round_trip = config_from_approval_policies(policies).approvers[0]
    assert round_trip.arguments == {"action": "key"}
    assert round_trip.params == {"decision": "reject"}


if __name__ == "__main__":
    test_approve_escalate()


async def test_raising_viewer_rejects_call() -> None:
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model._call_tools import execute_tools
    from inspect_ai.model._chat_message import ChatMessageAssistant
    from inspect_ai.tool._tool_def import ToolDef

    def raising_viewer(call: ToolCall) -> ToolCallView:
        raise KeyError("missing")

    init_transcript(Transcript())
    calls: list[ToolCall] = []
    call = ToolCall(id="1", function="addition", arguments={"x": 1, "y": 1})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [ToolDef(addition(), viewer=raising_viewer)],
        approval=[ApprovalPolicy(recording_approver(calls), "*")],
    )

    # the approver was not asked to decide on a fallback rendering
    assert calls == []
    message = messages[-1]
    assert isinstance(message, ChatMessageTool)
    assert message.error is not None
    assert message.error.type == "approval"
    assert "viewer for tool 'addition' failed" in message.error.message

    # the rejection is in the log
    approvals = [e for e in transcript().events if isinstance(e, ApprovalEvent)]
    assert len(approvals) == 1
    assert approvals[0].decision == "reject"
    assert approvals[0].view is None
