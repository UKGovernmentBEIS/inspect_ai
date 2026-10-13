from dataclasses import replace
from typing import Any

import pytest
from rich.console import Console

from inspect_ai import Task, eval
from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._human import acp as acp_module
from inspect_ai.approval._human import approver as approver_module
from inspect_ai.approval._human import panel as panel_module
from inspect_ai.approval._human.manager import (
    HumanApprovalManager,
    human_approval_manager,
)
from inspect_ai.approval._human.util import render_tool_approval
from inspect_ai.dataset import Sample
from inspect_ai.event import ToolEvent
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ChatMessageTool,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolCallContent, ToolCallView, tool
from inspect_ai.tool._tool_call import substitute_tool_call_content

try:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Protocol,
        Reported,
        human,
        protocol,
        sequential,
    )

    from inspect_ai._sentinel._dispatch import _Host
except ImportError:
    pytest.skip("inspect_sentinel is not installed", allow_module_level=True)


@tool
def addition() -> Tool:
    async def execute(x: int, y: int) -> str:
        """Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.
        """
        return str(x + y)

    return execute


def shout_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(title="Shout", format="markdown", content="**{{text}}**")
    )


@tool(viewer=shout_viewer)
def shout() -> Tool:
    async def execute(text: str) -> str:
        """Shout some text.

        Args:
            text: Text to shout.
        """
        return text.upper()

    return execute


@protocol
def h_escalate_turn() -> Protocol:
    async def unsure(context: Context, step: AfterGenerate) -> Decision | None:
        if step.output.message.tool_calls:
            return Decision.escalate("two calls together, {{x}}")
        return Decision.proceed()

    return unsure


@protocol
def h_escalate() -> Protocol:
    async def unsure(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.escalate("adds {{x}} suspiciously")

    return unsure


class Panel:
    def __init__(
        self, decision: ApprovalDecision, explanation: str | None = None
    ) -> None:
        self.decision = decision
        self.explanation = explanation
        self.views: list[ToolCallView] = []
        self.choices: list[list[str]] = []
        self.messages: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def acp(**kwargs: object) -> Approval | None:
            return None

        async def panel(
            message: str,
            call: ToolCall,
            view: ToolCallView,
            history: object,
            choices: list[str],
        ) -> Approval:
            self.messages.append(message)
            self.views.append(view)
            self.choices.append(choices)
            return Approval(decision=self.decision, explanation=self.explanation)

        monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
        monkeypatch.setattr(approver_module, "panel_approval", panel)

    def content(self) -> str:
        [view] = self.views
        assert view.call is not None
        return view.call.content


def run(sentinel: Any, **kwargs: Any) -> EvalLog:
    outputs = [
        ModelOutput.for_tool_call(
            "mockllm/model",
            tool_name="addition",
            tool_arguments={"x": 1, "y": 1},
            content="Adding now.",
        ),
        ModelOutput.from_content("mockllm/model", content="done"),
    ]
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        sentinel=sentinel,
    )
    model = get_model("mockllm/model", custom_outputs=outputs, memoize=False)
    return eval(task, model=model, **kwargs)[0]


def tool_messages(log: EvalLog) -> list[ChatMessageTool]:
    assert log.samples
    return [m for m in log.samples[0].messages if isinstance(m, ChatMessageTool)]


def escalated_to_human() -> Any:
    return sequential([h_escalate(), human(stages=["tool_call"])])


def test_an_escalation_asks_the_person_and_approve_runs_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    log = run(escalated_to_human())

    assert log.status == "success", log.error
    assert panel.choices == [["approve", "reject", "terminate"]]
    assert panel.messages == ["Adding now."]
    content = panel.content()
    assert (
        "**Escalated by**\n\n```\n- h_escalate: adds { {x}} suspiciously\n```"
        in content
    )
    assert content.index("Escalated by") < content.index("addition(")
    [message] = tool_messages(log)
    assert message.error is None
    assert message.text == "2"


def test_a_rejection_blocks_the_call_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("reject", "use subtraction").install(monkeypatch)

    log = run(escalated_to_human())

    assert log.status == "success", log.error
    [message] = tool_messages(log)
    assert message.error is not None
    assert message.error.type == "approval"
    assert message.error.message == "use subtraction"


def test_no_escalations_shows_the_plain_view(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    log = run(human(stages=["tool_call"]))

    assert log.status == "success", log.error
    assert "Escalated by" not in panel.content()


def test_after_a_call_the_person_sees_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    log = run(human(stages=["tool_result"]))

    assert log.status == "success", log.error
    assert panel.choices == [["approve", "terminate"]]
    assert "**Result**\n\n```\n2\n```" in panel.content()


def step(
    after: bool = False,
    view: ToolCallView | None = None,
    escalations: tuple[Reported[Decision], ...] = (),
) -> BeforeToolCall | AfterToolCall:
    call = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
    view = view or ToolCallView()
    if after:
        result = ChatMessageTool(content="2", tool_call_id="c1", function="addition")
        return AfterToolCall(
            "", "Adding.", call, result, "2", view, [], [], escalations
        )
    return BeforeToolCall("", "Adding.", call, view, [], [], escalations)


def escalation(explanation: str) -> tuple[Reported[Decision], ...]:
    return (Reported("monitor", "monitor", Decision.escalate(explanation), "check"),)


MARKDOWN_VIEW = ToolCallView(
    call=ToolCallContent(format="markdown", content="```python\naddition(1, 1)\n```")
)
TEXT_VIEW = ToolCallView(call=ToolCallContent(format="text", content="addition(1, 1)"))


@pytest.mark.parametrize("view", [MARKDOWN_VIEW, TEXT_VIEW])
async def test_placeholders_in_an_escalation_are_not_substituted(
    monkeypatch: pytest.MonkeyPatch, view: ToolCallView
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    await _Host().ask_human(
        step(view=view, escalations=escalation("adds {{{x}}}")), ["approve"]
    )

    [shown] = panel.views
    assert shown.call is not None
    rendered = substitute_tool_call_content(shown.call, {"x": 1, "y": 1})
    assert "adds { { {x}}}" in rendered.content


async def test_an_escalation_cannot_inject_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)
    injected = "fine\n```\n\n```python\ndelete_everything()\n```\n```"

    await _Host().ask_human(
        step(view=MARKDOWN_VIEW, escalations=escalation(injected)), ["approve"]
    )

    content = panel.content()
    fenced = f"````\n- monitor: {injected}\n````"
    assert content.startswith(f"**Escalated by**\n\n{fenced}\n\n")
    assert content.endswith("```python\naddition(1, 1)\n```")


@pytest.mark.parametrize(
    "after, choices, answered, expected",
    [
        # an ACP client dismissing the request reports reject
        (False, ["approve", "terminate"], "reject", "terminate"),
        (True, ["approve", "terminate"], "reject", "terminate"),
        # the console's Enter default is approve
        (False, ["reject", "terminate"], "approve", "reject"),
        (False, ["terminate"], "approve", "terminate"),
        (True, ["terminate"], "approve", "terminate"),
    ],
)
async def test_an_answer_that_was_not_offered_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    after: bool,
    choices: list[str],
    answered: ApprovalDecision,
    expected: str,
) -> None:
    Panel(answered, "dismissed").install(monkeypatch)

    answer = await _Host().ask_human(step(after), choices)

    assert answer.decision == expected
    assert answer.reason is not None
    assert f"{answered}: dismissed" in answer.reason


def test_a_dismissal_terminates_when_only_approve_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("reject", "dismissed").install(monkeypatch)

    log = run(human(stages=["tool_call"], choices=["approve"]))

    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.error is None
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert all(m.text != "2" for m in tool_messages(log))
    tool_events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert [e.failed for e in tool_events] == [True]


async def test_modify_cannot_be_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    with pytest.raises(NotImplementedError, match="cannot edit a tool call"):
        await _Host().ask_human(step(), ["approve", "modify"])
    assert panel.views == []


def test_a_pending_request_is_withdrawn_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def acp(**kwargs: object) -> Approval | None:
        return None

    managers: list[HumanApprovalManager] = []
    changes: list[str] = []

    async def show_panel(*args: object) -> None:
        manager = human_approval_manager()
        if not managers:
            managers.append(manager)
            manager.on_change(changes.append)

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    monkeypatch.setattr(panel_module, "input_panel", show_panel)

    log = run(human(stages=["tool_call"]), time_limit=1)

    assert log.samples
    assert log.samples[0].limit is not None
    assert log.samples[0].limit.type == "time"
    assert changes == ["add", "remove"]
    assert managers[0].approval_requests() == []


ADD = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
SHOUT = ToolCall(id="c2", function="shout", arguments={"text": "hello"})


def turn_output(*calls: ToolCall, content: str = "Adding and shouting.") -> ModelOutput:
    message = ChatMessageAssistant(
        content=content, model="mockllm/model", tool_calls=list(calls) or None
    )
    return ModelOutput(
        model="mockllm/model",
        choices=[ChatCompletionChoice(message=message, stop_reason="tool_calls")],
    )


def run_turn(sentinel: Any) -> EvalLog:
    outputs = [
        turn_output(ADD, SHOUT),
        ModelOutput.from_content("mockllm/model", content="done"),
    ]
    task = Task(
        dataset=[Sample(input="Add 1 and 1, and shout hello.")],
        solver=[use_tools(addition(), shout()), generate()],
        sentinel=sentinel,
    )
    model = get_model("mockllm/model", custom_outputs=outputs, memoize=False)
    return eval(task, model=model)[0]


def turn_escalated_to_human() -> Any:
    return sequential([h_escalate_turn(), human(stages=["model_output"])])


def test_an_escalated_turn_shows_every_call_and_approve_runs_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    log = run_turn(turn_escalated_to_human())

    assert log.status == "success", log.error
    assert panel.choices == [["approve", "terminate"]]
    assert panel.messages == ["Adding and shouting."]
    content = panel.content()
    escalated = (
        "**Escalated by**\n\n```\n- h_escalate_turn: two calls together, { {x}}\n```"
    )
    assert content.startswith(escalated)
    # each call as it is rendered before a call: the default view, and the
    # tool's own viewer with its placeholders filled in
    assert content.index("addition(x=1, y=1)") < content.index("**Shout**\n\n**hello**")
    assert [m.text for m in tool_messages(log)] == ["2", "HELLO"]


def test_a_terminated_turn_runs_none_of_its_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("terminate", "deletes the repo").install(monkeypatch)

    log = run_turn(turn_escalated_to_human())

    assert log.status == "success", log.error
    assert log.samples
    sample = log.samples[0]
    assert sample.error is None
    assert sample.limit is not None
    assert sample.limit.type == "operator"
    assert tool_messages(log) == []
    assert not [e for e in sample.events if isinstance(e, ToolEvent)]


def turn_step(
    *calls: ToolCall, escalations: tuple[Reported[Decision], ...] = ()
) -> AfterGenerate:
    return AfterGenerate(
        model="mockllm/model",
        conversation="",
        input=[],
        history=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=turn_output(*calls),
        escalations=escalations,
    )


VIEWED_SHOUT = replace(SHOUT, view=shout_viewer(SHOUT).call)


async def test_every_surface_is_handed_the_whole_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[dict[str, Any]] = []

    async def acp(**kwargs: Any) -> Approval | None:
        asked.append(kwargs)
        return Approval(decision="approve")

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)

    answer = await _Host().ask_human(
        turn_step(ADD, VIEWED_SHOUT, escalations=escalation("together")),
        ["approve", "terminate"],
    )

    assert answer.decision == "approve"
    [kwargs] = asked
    call, view = kwargs["call"], kwargs["view"]
    assert call.function == "Assistant turn: addition, shout"
    assert call.arguments == {}
    assert kwargs["message"] == "Adding and shouting."

    # ACP: one permission card for the turn
    request = acp_module._build_request(
        session_id="s", call=call, view=view, choices=kwargs["choices"]
    )
    assert request.tool_call.title == "Assistant turn: addition, shout"
    [block] = request.tool_call.content or []
    shown = block.content.text
    assert shown.index("together") < shown.index("addition(") < shown.index("hello")

    # the approval panel and the console render it with render_tool_approval
    console = Console(record=True, width=80)
    for renderable in render_tool_approval(kwargs["message"], view, call.arguments):
        console.print(renderable)
    text = console.export_text()
    for expected in ["Adding and shouting.", "together", "addition(", "Shout", "hello"]:
        assert expected in text


async def test_a_turn_with_no_calls_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    await _Host().ask_human(turn_step(), ["approve", "terminate"])

    assert panel.content() == "The turn makes no tool calls."


async def test_a_dismissed_turn_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    Panel("reject", "dismissed").install(monkeypatch)

    answer = await _Host().ask_human(turn_step(ADD), ["approve", "terminate"])

    assert answer.decision == "terminate"
    assert answer.reason is not None
    assert "reject: dismissed" in answer.reason


async def test_a_turn_cannot_be_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    with pytest.raises(ValueError, match="cannot offer 'reject' at the model_output"):
        await _Host().ask_human(turn_step(ADD), ["approve", "reject"])
    assert panel.views == []


async def test_a_person_cannot_be_asked_before_a_generate() -> None:
    before = BeforeGenerate(
        model="mockllm/model",
        conversation="",
        input=[],
        history=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    with pytest.raises(NotImplementedError, match="model_input"):
        await _Host().ask_human(before, ["approve"])
