from typing import Any

import pytest

from inspect_ai import Task, eval
from inspect_ai._sentinel._dispatch import _Host
from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._human import acp as acp_module
from inspect_ai.approval._human import approver as approver_module
from inspect_ai.approval._human import panel as panel_module
from inspect_ai.approval._human.manager import (
    HumanApprovalManager,
    human_approval_manager,
)
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ChatMessageTool,
    ModelOutput,
    get_model,
)
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolCallView, tool

try:
    from inspect_sentinel import (
        AfterToolCall,
        BeforeToolCall,
        Context,
        Decision,
        Protocol,
        human,
        protocol,
        sequential,
    )
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
    assert "**Escalated by**\n\n- h_escalate: adds { {x}} suspiciously" in content
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


def step(after: bool = False) -> BeforeToolCall | AfterToolCall:
    call = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
    view = ToolCallView()
    if after:
        result = ChatMessageTool(content="2", tool_call_id="c1", function="addition")
        return AfterToolCall("", "Adding.", call, result, "2", view, [], [])
    return BeforeToolCall("", "Adding.", call, view, [], [])


@pytest.mark.parametrize(
    "after, choices, expected",
    [
        (False, ["approve", "reject", "terminate"], "reject"),
        (False, ["approve", "terminate"], "terminate"),
        (True, ["approve", "terminate"], "terminate"),
    ],
)
async def test_an_answer_that_was_not_offered_fails_closed(
    monkeypatch: pytest.MonkeyPatch, after: bool, choices: list[str], expected: str
) -> None:
    # an ACP client dismissing the request reports reject
    Panel("escalate", "dismissed").install(monkeypatch)

    answer = await _Host().ask_human(step(after), choices)

    assert answer.decision == expected
    assert answer.reason is not None
    assert "escalate: dismissed" in answer.reason


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
