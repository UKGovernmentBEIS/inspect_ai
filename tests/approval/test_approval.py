import fnmatch
import logging
import ntpath
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, NamedTuple

import pytest
from pydantic_core import PydanticSerializationError

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
    config_from_approval_policies,
    policy_approver,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.model import ChatMessage, ChatMessageTool, Model, ModelOutput, get_model
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
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
