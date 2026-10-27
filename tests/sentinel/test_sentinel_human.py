import asyncio
import io
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, NamedTuple
from unittest.mock import MagicMock

import anyio
import pytest
from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    RequestPermissionRequest,
    RequestPermissionResponse,
)
from markdown_it import MarkdownIt
from rich.console import Console
from rich.markdown import Markdown
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent import handoff, react
from inspect_ai.agent._acp.tui.state import (
    PendingApproval,
    SessionState,
    ToolCallState,
)
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
from inspect_ai.event import (
    ModelEvent,
    SentinelEvent,
    SpanBeginEvent,
    SpanEndEvent,
    ToolEvent,
)
from inspect_ai.log import EvalLog, transcript
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._display import display_conversation_assistant_message
from inspect_ai.model._model import use_model_event_sink
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolCallContent, ToolCallView, tool
from inspect_ai.tool._tool_call import substitute_tool_call_content
from inspect_ai.tool._tools._execute import code_viewer
from inspect_ai.util._span import span

# mypy checks the tests against inspect_sentinel's API; they run on the fake
if TYPE_CHECKING:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        HumanAnswer,
        HumanDecision,
        Monitor,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        Reported,
        monitor,
        protocol,
    )

    from inspect_ai._sentinel._dispatch import _HostNative
else:
    from test_helpers.fake_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        HumanAnswer,
        HumanDecision,
        Monitor,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        Reported,
        monitor,
        protocol,
    )

pytestmark = pytest.mark.usefixtures("fake_sentinel")


def host_native() -> "_HostNative":
    from inspect_ai._sentinel._dispatch import _HostNative

    return _HostNative(None)


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


def escalation(explanation: str) -> Escalations:
    return (Reported("monitor", "monitor", Decision.escalate(explanation), "check"),)


def answered(answer: HumanAnswer) -> Decision:
    if answer.decision == "approve":
        return Decision.proceed(answer.reason)
    if answer.decision == "reject":
        return Decision.reject(answer.reason, message=answer.reason)
    return Decision.terminate(answer.reason)


# kept for later steps as inspect_sentinel's human() decisions are
@protocol(name="inspect_sentinel/human")
def h_ask(
    stage: str, choices: list[str], escalated: str | None = None
) -> ProtocolGroup:
    """Ask the person at `stage`, after an escalation that explains `escalated`."""
    escalated_by = escalation(escalated) if escalated is not None else ()

    async def tool_call(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        return answered(await context.host.ask_human(step, escalated_by, choices))

    async def tool_result(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        return answered(await context.host.ask_human(step, escalated_by, choices))

    async def model_output(
        context: Context, step: AfterGenerate, escalations: Escalations
    ) -> Decision | None:
        if not step.output.message.tool_calls:
            return None
        return answered(await context.host.ask_human(step, escalated_by, choices))

    stages: dict[str, Protocol] = {
        "tool_call": tool_call,
        "tool_result": tool_result,
        "model_output": model_output,
    }
    return ProtocolGroup(stages[stage])


class Panel:
    def __init__(
        self, decision: ApprovalDecision, explanation: str | None = None
    ) -> None:
        self.decision = decision
        self.explanation = explanation
        self.views: list[ToolCallView] = []
        self.choices: list[list[str]] = []
        self.messages: list[str] = []
        self.histories: list[object] = []

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
            self.histories.append(history)
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


ALL_CHOICES = ["approve", "reject", "terminate"]


def escalated_to_human() -> Any:
    return h_ask("tool_call", ALL_CHOICES, escalated="adds {{x}} suspiciously")


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
        "**Escalated by**\n\n```\n- monitor: adds { {x}} suspiciously\n```" in content
    )
    assert content.index("Escalated by") < content.index("addition(")
    [message] = tool_messages(log)
    assert message.error is None
    assert message.text == "2"


def test_an_approval_records_the_persons_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve", "addition is expected here").install(monkeypatch)

    log = run(escalated_to_human())

    assert log.status == "success", log.error
    assert log.samples
    [approval] = [
        e
        for e in log.samples[0].events
        if isinstance(e, SentinelEvent) and e.factory == "inspect_sentinel/human"
    ]
    assert approval.action == "proceed"
    assert approval.explanation == "addition is expected here"


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

    log = run(h_ask("tool_call", ALL_CHOICES))

    assert log.status == "success", log.error
    assert "Escalated by" not in panel.content()


def test_after_a_call_the_person_sees_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    log = run(h_ask("tool_result", ["approve", "terminate"]))

    assert log.status == "success", log.error
    assert panel.choices == [["approve", "terminate"]]
    assert "**Result**\n\n```\n2\n```" in panel.content()


def step(
    after: bool = False, view: ToolCallView | None = None
) -> BeforeToolCall | AfterToolCall:
    call = ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
    view = view or ToolCallView()
    if after:
        result = ChatMessageTool(content="2", tool_call_id="c1", function="addition")
        return AfterToolCall(
            conversation="",
            message="Adding.",
            message_id="m1",
            call=call,
            result=result,
            output="2",
            view=view,
            input=[],
            agent_messages=[],
        )
    return BeforeToolCall(
        conversation="",
        message="Adding.",
        message_id="m1",
        call=call,
        view=view,
        input=[],
        agent_messages=[],
    )


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

    await host_native().ask_human(
        step(view=view), escalation("adds {{{x}}}"), ["approve"]
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

    await host_native().ask_human(
        step(view=MARKDOWN_VIEW), escalation(injected), ["approve"]
    )

    content = panel.content()
    fenced = f"````\n- monitor: {injected}\n````"
    assert content.startswith(f"**Escalated by**\n\n{fenced}\n\n")
    assert content.endswith("```python\naddition(1, 1)\n```")


HISTORY: list[ChatMessage] = [
    ChatMessageUser(content="What is 1 + 1?"),
    ChatMessageAssistant(content="Adding."),
]
INPUT: list[ChatMessage] = [ChatMessageUser(content="What is 1 + 1?")]


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize(
    "history, model_input, shown",
    [
        (HISTORY, INPUT, HISTORY),
        # a host that could not provide history: show what the model saw
        (None, INPUT, INPUT),
        (None, None, []),
    ],
    ids=["history", "no-history", "neither"],
)
async def test_the_person_sees_history_or_else_what_the_model_saw(
    monkeypatch: pytest.MonkeyPatch,
    after: bool,
    history: list[ChatMessage] | None,
    model_input: list[ChatMessage] | None,
    shown: list[ChatMessage],
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    await host_native().ask_human(
        replace(step(after), agent_messages=history, input=model_input), (), ["approve"]
    )

    assert panel.histories == [shown]


@pytest.mark.parametrize(
    "history, shown",
    [(HISTORY, HISTORY), (None, INPUT)],
    ids=["history", "no-history"],
)
async def test_after_a_generate_the_person_sees_history_or_else_what_the_model_saw(
    monkeypatch: pytest.MonkeyPatch,
    history: list[ChatMessage] | None,
    shown: list[ChatMessage],
) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    await host_native().ask_human(
        replace(turn_step(ADD), agent_messages=history, input=INPUT),
        (),
        ["approve", "terminate"],
    )

    assert panel.histories == [shown]


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

    answer = await host_native().ask_human(step(after), (), choices)

    assert answer.decision == expected
    assert answer.reason is not None
    # later steps read this answer, so it says the person did not choose
    assert answer.reason.startswith(
        "The person closed the prompt without choosing; failing closed"
    )
    assert f"{answered}: dismissed" in answer.reason


def test_a_dismissal_terminates_when_only_approve_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("reject", "dismissed").install(monkeypatch)

    log = run(h_ask("tool_call", ["approve"]))

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
        await host_native().ask_human(step(), (), ["approve", "modify"])
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

    log = run(h_ask("tool_call", ALL_CHOICES), time_limit=1)

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
    return h_ask(
        "model_output", ["approve", "terminate"], escalated="two calls together, {{x}}"
    )


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
    escalated = "**Escalated by**\n\n```\n- monitor: two calls together, { {x}}\n```"
    assert content.startswith(escalated)
    # each call as the transcript shows it: the default view, and the tool's
    # own viewer with its placeholders filled in
    assert content.index("addition(x=1, y=1)") < content.index("**hello**")
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


def turn_step(*calls: ToolCall, content: str = "Adding and shouting.") -> AfterGenerate:
    return AfterGenerate(
        model="mockllm/model",
        conversation="",
        input=[],
        agent_messages=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=turn_output(*calls, content=content),
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

    answer = await host_native().ask_human(
        turn_step(ADD, VIEWED_SHOUT), escalation("together"), ["approve", "terminate"]
    )

    assert answer.decision == "approve"
    [kwargs] = asked
    call, view = kwargs["call"], kwargs["view"]
    assert call.function == "Assistant turn: 2 tool calls (addition, shout)"
    assert call.arguments == {}
    assert kwargs["message"] == "Adding and shouting."
    assert "hidden or control characters" not in view.call.content

    # ACP: one permission card for the turn
    request = acp_module._build_request(
        session_id="s", call=call, view=view, choices=kwargs["choices"]
    )
    assert request.tool_call.title == "Assistant turn: 2 tool calls (addition, shout)"
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

    await host_native().ask_human(turn_step(), (), ["approve", "terminate"])

    assert panel.content() == "**The turn makes no tool calls.**"


async def test_a_dismissed_turn_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    Panel("reject", "dismissed").install(monkeypatch)

    answer = await host_native().ask_human(turn_step(ADD), (), ["approve", "terminate"])

    assert answer.decision == "terminate"
    assert answer.reason is not None
    assert "reject: dismissed" in answer.reason


async def test_a_turn_cannot_be_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    panel = Panel("approve")
    panel.install(monkeypatch)

    with pytest.raises(ValueError, match="cannot offer 'reject' at the model_output"):
        await host_native().ask_human(turn_step(ADD), (), ["approve", "reject"])
    assert panel.views == []


async def test_a_person_cannot_be_asked_before_a_generate() -> None:
    before = BeforeGenerate(
        model="mockllm/model",
        conversation="",
        input=[],
        agent_messages=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
    )
    with pytest.raises(NotImplementedError, match="model_input"):
        await host_native().ask_human(before, (), ["approve"])


BASH = code_viewer("bash", "cmd")


def bash_call(id: str, cmd: str) -> ToolCall:
    call = ToolCall(id=id, function="bash", arguments={"cmd": cmd})
    return replace(call, view=BASH(call).call)


# save the cursor, go up eight lines, wipe the line, write a benign one there,
# and restore the cursor: on a terminal, call 3's line would read "echo done"
COVER = "\x1b7\x1b[8A\x1b[2K\x1b[1G│  echo done\x1b8"
# right-to-left override: what follows would read reversed
RLO = "\u202e"

NOTICE = (
    "This turn contains hidden or control characters, "
    f"shown as {chr(0x2039)}U+…{chr(0x203A)}."
)


def marker(code: str) -> str:
    return f"{chr(0x2039)}U+{code}{chr(0x203A)}"


# a call whose function name and viewer title try to add structure, and to
# move the cursor
HEADER = f"bash\n\n<!-- **x** [x](y) ``{COVER}{RLO}"
NAMED = ToolCall(
    id="c2",
    function=HEADER,
    arguments={},
    view=ToolCallContent(title=HEADER, format="markdown", content="named"),
)
NOTES = ToolCall(
    id="c4",
    function="notes",
    arguments={},
    view=ToolCallContent(format="text", content=f"**not bold**\n<!--{COVER}{RLO}"),
)


def code_blocks(markdown: str) -> list[str]:
    tokens = MarkdownIt("commonmark").parse(markdown)
    assert not [t for t in tokens if t.type == "html_block"]
    return [t.content[:-1] for t in tokens if t.type == "fence"]


def rendered(markdown: str) -> str:
    console = Console(record=True, width=120)
    console.print(Markdown(markdown))
    return console.export_text()


@pytest.mark.parametrize(
    "first",
    [
        # closes the fence and opens an HTML comment that would swallow the rest
        "ls -la\n```\n<!--",
        # closes the fence and starts a link reference definition
        "ls -la\n```\n[x]: <",
        # closes the fence and writes a second call of its own
        "ls -la\n````\n\n---\n\n**Call 2 of 4:** bash\n\n```bash\necho hello",
    ],
)
async def test_no_call_can_hide_or_pass_for_another(
    monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    asked: list[dict[str, Any]] = []

    async def acp(**kwargs: Any) -> Approval | None:
        asked.append(kwargs)
        return Approval(decision="approve")

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    calls = (bash_call("c1", first), NAMED, bash_call("c3", "rm -rf /srv/data"), NOTES)
    step = turn_step(*calls, content=f"Tidying up.{COVER}{RLO}")

    await host_native().ask_human(
        step, escalation(f"quotes the agent: {COVER}"), ["approve", "terminate"]
    )

    [kwargs] = asked
    call, view = kwargs["call"], kwargs["view"]
    # the count comes from the turn, not from anything the agent wrote, and
    # the title is one line
    assert call.function.startswith("Assistant turn: 4 tool calls (bash ×2, bash ")
    assert "\n" not in call.function
    assert "\x1b" not in call.function and RLO not in call.function
    # each call's content is one code block of its own, whatever it contains,
    # with control and bidi characters shown as escapes
    esc = marker("001B")
    cover = f"{esc}7{esc}[8A{esc}[2K{esc}[1G│  echo done{esc}8"
    visible = cover + marker("202E")
    assert code_blocks(view.call.content) == [
        f"- monitor: quotes the agent: {cover}",
        first,
        "named",
        "rm -rf /srv/data",
        f"**not bold**\n<!--{visible}",
    ]
    assert kwargs["message"] == f"Tidying up.{visible}"
    request = acp_module._build_request(
        session_id="s", call=call, view=view, choices=kwargs["choices"]
    )
    [block] = request.tool_call.content or []
    assert code_blocks(block.content.text) == code_blocks(view.call.content)
    # the panel and console write to a terminal: nothing the agent wrote may
    # reach it as a control sequence
    terminal = io.StringIO()
    console = Console(file=terminal, force_terminal=True, width=120, record=True)
    for renderable in render_tool_approval(kwargs["message"], view, call.arguments):
        console.print(renderable)
    console.print(Markdown(block.content.text))
    for agent_sequence in ["\x1b7", "\x1b8", "\x1b[8A", "\x1b[2K", RLO]:
        assert agent_sequence not in terminal.getvalue()
    notice = NOTICE
    assert f"**{notice}**" in view.call.content
    for text in [console.export_text(), rendered(block.content.text)]:
        assert "The turn makes 4 tool calls." in text
        assert notice in text
        assert "rm -rf /srv/data" in text
        assert "**not bold**" in text
        assert "<!-- **x** [x](y) ``" in text
        assert [line for line in text.splitlines() if "Call 3 of 4" in line]
        assert [line for line in text.splitlines() if "Call 4 of 4" in line]


async def turn_view(
    monkeypatch: pytest.MonkeyPatch, step: AfterGenerate
) -> tuple[str, str]:
    """The message and view content the surfaces are handed for a turn."""
    asked: list[dict[str, Any]] = []

    async def acp(**kwargs: Any) -> Approval | None:
        asked.append(kwargs)
        return Approval(decision="approve")

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    await host_native().ask_human(step, (), ["approve", "terminate"])
    [kwargs] = asked
    return kwargs["message"], kwargs["view"].call.content


async def test_a_real_escape_and_a_typed_one_look_different(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = bash_call("c1", "printf 'a\x1b'")
    typed = bash_call("c2", "printf 'a\\x1b'")
    # in bash this runs rm; it must read the same way when shown
    shell = 'echo \\"; rm -rf /srv/data; echo \\"'
    hidden = bash_call("c3", shell + chr(0x200B))

    _, content = await turn_view(monkeypatch, turn_step(real, typed, hidden))

    assert code_blocks(content) == [
        f"printf 'a{marker('001B')}'",
        "printf 'a\\x1b'",
        shell + marker("200B"),
    ]


async def test_control_characters_in_the_text_alone_are_noticed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = turn_step(ADD, content="Adding.\x1b[2J")

    message, content = await turn_view(monkeypatch, step)

    assert message == f"Adding.{marker('001B')}[2J"
    assert f"**{NOTICE}**" in content


def test_the_conversation_display_prints_the_turn_without_control_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `--display conversation` prints the turn just before the person is
    # asked about it: clearing the screen and confining scrolling to the top
    # rows would leave the prompt's calls off screen
    terminal = io.StringIO()
    console = Console(file=terminal, force_terminal=True, width=120, record=True)
    monkeypatch.setattr("inspect_ai.util._conversation.print", console.print)
    attack = "\x1b[2J\x1b[1;9r"
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning=f"plan{attack}"),
            ContentText(text=f"Tidying up.{attack}{RLO}"),
        ],
        tool_calls=[
            bash_call("c1", f"ls -la{attack}"),
            bash_call("c2", "rm -rf /srv/data"),
            ToolCall(id="c3", function=f"think{attack}", arguments={"thought": attack}),
        ],
    )

    display_conversation_assistant_message(message)

    for sequence in ["\x1b[2J", "\x1b[1;9r", RLO]:
        assert sequence not in terminal.getvalue()
    shown = console.export_text()
    assert "rm -rf /srv/data" in shown
    esc = marker("001B")
    for text in [
        f"plan{esc}[2J",
        f"Tidying up.{esc}[2J",
        f"ls -la{esc}[2J",
        f"think{esc}[2J",
    ]:
        assert text in shown


class TuiSession:
    """An ACP transport with the Inspect ACP TUI attached, and an observer.

    The driver answers each permission request as the TUI does: with
    `answer`, by dismissing it when `answer` is None, or by leaving it open
    and cancelling `scope`. Every published notification reaches both the
    driver's state and the observer's, a second client that never sees the
    request.
    """

    session_id = "s"

    def __init__(
        self, answer: str | None, scope: anyio.CancelScope | None = None
    ) -> None:
        self.state = SessionState()
        self.observer = SessionState()
        self.answer = answer
        self.scope = scope

    def approver_driver_chain(self) -> list["TuiSession"]:
        return [self]

    def subscribe_approver_attach(self, callback: Any) -> Any:
        return lambda: None

    def publish(self, update: Any) -> None:
        self.state.consume(update)
        self.observer.consume(update)

    async def drain_notifications(self) -> None:
        pass

    async def request_permission(
        self, request: RequestPermissionRequest
    ) -> RequestPermissionResponse:
        self.state.consume_approval_request(PendingApproval(request, asyncio.Event()))
        id = request.tool_call.tool_call_id
        if self.scope is not None:
            self.scope.cancel()
            await anyio.sleep_forever()
        if self.answer is None:
            self.state.resolve_approval(id, cancelled=True)
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        self.state.resolve_approval(id, option_id=self.answer)
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=self.answer)
        )


@pytest.fixture
def tui(monkeypatch: pytest.MonkeyPatch) -> Callable[[TuiSession], None]:
    def attach(session: TuiSession) -> None:
        sample = MagicMock()
        sample.acp_transport = session
        monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)

    monkeypatch.setattr(
        "inspect_ai.agent._acp.server.acp_server_accepting_clients", lambda: True
    )
    return attach


def only_card(state: SessionState) -> ToolCallState:
    [card] = state.items
    assert isinstance(card, ToolCallState)
    return card


@pytest.mark.parametrize(
    "answer, decision, status",
    [
        ("approve", "approve", "completed"),
        ("terminate", "terminate", "completed"),
        # a dismissed prompt fails closed
        (None, "terminate", "failed"),
    ],
)
@pytest.mark.parametrize("calls", [(ADD, SHOUT), ()])
@skip_if_trio
async def test_an_acp_turn_card_is_finished_once_the_prompt_ends(
    tui: Callable[[TuiSession], None],
    answer: str | None,
    decision: str,
    status: str,
    calls: tuple[ToolCall, ...],
) -> None:
    session = TuiSession(answer)
    tui(session)

    result = await host_native().ask_human(
        turn_step(*calls), (), ["approve", "terminate"]
    )

    assert result.decision == decision
    card = only_card(session.state)
    assert card.tool_call_id not in {call.id for call in calls}
    assert card.status == status
    assert session.state.tools_in_flight == 0
    assert session.state.cancel_tool_call_ids == []
    session.state.mark_complete()
    assert card.status == status
    # a client that never saw the request gets the whole card, not an empty one
    seen = only_card(session.observer)
    assert (seen.tool_call_id, seen.status) == (card.tool_call_id, status)
    assert seen.title == card.title
    assert seen.title is not None and seen.title.startswith("Assistant turn")
    assert seen.content


@skip_if_trio
async def test_an_acp_turn_card_fails_when_the_prompt_is_cancelled(
    tui: Callable[[TuiSession], None],
) -> None:
    with anyio.CancelScope() as scope:
        session = TuiSession("approve", scope)
        tui(session)
        await host_native().ask_human(turn_step(ADD), (), ["approve", "terminate"])

    assert scope.cancelled_caught
    card = only_card(session.state)
    assert card.status == "failed"
    assert session.state.tools_in_flight == 0
    assert only_card(session.observer).status == "failed"


@skip_if_trio
async def test_each_turn_prompt_has_a_card_of_its_own(
    tui: Callable[[TuiSession], None],
) -> None:
    session = TuiSession("approve")
    tui(session)

    for _ in range(2):
        await host_native().ask_human(turn_step(ADD), (), ["approve", "terminate"])

    first, second = session.state.items
    assert isinstance(first, ToolCallState) and isinstance(second, ToolCallState)
    assert first.tool_call_id != second.tool_call_id
    assert [first.status, second.status] == ["completed", "completed"]


# human decisions


class Seen(NamedTuple):
    stage: str
    conversation: str
    subject: str
    decisions: tuple[HumanDecision, ...] | None


@monitor
def h_spy(seen: Any) -> MonitorGroup:
    async def tool_call(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(
            Seen("tool_call", step.conversation, step.call.id, step.human_decisions)
        )
        return None

    async def tool_result(context: Context, step: AfterToolCall) -> Observation | None:
        seen.append(
            Seen("tool_result", step.conversation, step.call.id, step.human_decisions)
        )
        return None

    async def model_output(context: Context, step: AfterGenerate) -> Observation | None:
        seen.append(
            Seen(
                "model_output",
                step.conversation,
                step.output.completion,
                step.human_decisions,
            )
        )
        return None

    return MonitorGroup(tool_call, tool_result, model_output)


def call_id(log: EvalLog, function: str = "addition") -> str:
    assert log.samples
    [found] = [
        call.id
        for m in log.samples[0].messages
        if isinstance(m, ChatMessageAssistant)
        for call in m.tool_calls or []
        if call.function == function
    ]
    return found


def kept(record: HumanDecision) -> tuple[Any, ...]:
    report = record.decided.report
    return (
        record.stage,
        record.step_id,
        record.call_ids,
        record.decided.name,
        report.action,
        report.explanation,
    )


def test_a_persons_approval_is_seen_at_later_steps_but_not_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve", "looks fine").install(monkeypatch)
    seen: list[Seen] = []

    log = run([escalated_to_human(), h_spy(seen)])

    assert log.status == "success", log.error
    call = call_id(log)
    # human() keeps the person's reason on an approve
    approved = ("tool_call", call, (call,), "human", "proceed", "looks fine")
    assert [
        (s.stage, s.subject, [kept(r) for r in s.decisions or ()]) for s in seen
    ] == [
        ("model_output", "Adding now.", []),
        ("tool_call", call, []),
        ("tool_result", call, [approved]),
        ("model_output", "done", [approved]),
    ]


def test_a_persons_rejection_is_seen_at_later_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("reject", "not that").install(monkeypatch)
    seen: list[Seen] = []

    log = run([escalated_to_human(), h_spy(seen)])

    assert log.status == "success", log.error
    [last] = [s for s in seen if s.subject == "done"]
    assert last.decisions is not None
    assert [kept(r) for r in last.decisions] == [
        ("tool_call", call_id(log), (call_id(log),), "human", "reject", "not that")
    ]


def test_a_turn_approval_is_seen_at_each_of_its_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    seen: list[Seen] = []

    log = run_turn([turn_escalated_to_human(), h_spy(seen)])

    assert log.status == "success", log.error
    assert log.samples
    [turn] = [
        m
        for m in log.samples[0].messages
        if isinstance(m, ChatMessageAssistant) and m.tool_calls
    ]
    [generate] = [
        e
        for e in log.samples[0].events
        if isinstance(e, ModelEvent) and e.output.message.id == turn.id
    ]
    assert generate.uuid is not None
    approved = ("model_output", generate.uuid, ("c1", "c2"), "human", "proceed", None)
    assert [
        (s.stage, s.subject, [kept(r) for r in s.decisions or ()]) for s in seen
    ] == [
        ("model_output", "Adding and shouting.", []),
        ("tool_call", "c1", [approved]),
        ("tool_result", "c1", [approved]),
        ("tool_call", "c2", [approved]),
        ("tool_result", "c2", [approved]),
        ("model_output", "done", [approved]),
    ]


def test_a_persons_decision_stays_in_its_own_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    seen: list[Seen] = []
    helper = react(
        name="helper",
        description="A helper agent.",
        tools=[addition()],
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    "mockllm/model",
                    tool_name="addition",
                    tool_arguments={"x": 2, "y": 3},
                ),
                ModelOutput.from_content("mockllm/model", content="helper done"),
            ],
            memoize=False,
        ),
        submit=False,
    )
    task = Task(
        dataset=[Sample(input="What is 2 + 3?")],
        solver=[use_tools(handoff(helper)), generate()],
        sentinel=[escalated_to_human(), h_spy(seen)],
    )
    parent_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="transfer_to_helper", tool_arguments={}
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )

    log = eval(task, model=parent_model)[0]

    assert log.status == "success", log.error
    # the helper's messages are not kept in the parent's, so take the calls'
    # ids from the steps: the parent's call, then the helper's
    (transfer, parent), (add, child) = [
        (s.subject, s.conversation) for s in seen if s.stage == "tool_call"
    ]
    assert parent != child
    by_call = {
        (s.stage, s.subject): [r.step_id for r in s.decisions or ()]
        for s in seen
        if s.stage != "model_output"
    }
    assert by_call == {
        ("tool_call", transfer): [],
        # the helper's own conversation holds none of its parent's decisions
        ("tool_call", add): [],
        ("tool_result", add): [add],
        ("tool_result", transfer): [transfer],
    }
    [done] = [s for s in seen if s.subject == "done"]
    assert [r.step_id for r in done.decisions or ()] == [transfer]


class StartsInSubAgent:
    """A model event sink that runs each generate in the span `sub-agent`."""

    def on_start(self, input: list[ChatMessage]) -> str | None:
        return "sub-agent"

    def on_pending(self, event: ModelEvent) -> None:
        transcript()._event(event)

    def on_complete(self, event: ModelEvent) -> None:
        transcript()._event_updated(event)


@solver
def h_sub_agent_turns_then_a_main_turn() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async with span("outer", type="agent", id="outer"):
            transcript()._event(
                SpanBeginEvent(
                    id="sub-agent", parent_id="outer", type="agent", name="sub"
                )
            )
            with use_model_event_sink(StartsInSubAgent()):
                await get_model().generate("Sub-agent turn.")
                await get_model().generate("Sub-agent again.")
            transcript()._event(SpanEndEvent(id="sub-agent"))
            state.output = await get_model().generate("Main turn.")
        return state

    return solve


def test_a_persons_decision_on_an_on_start_sink_s_turn_stays_in_its_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Panel("approve").install(monkeypatch)
    seen: list[Seen] = []
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            turn_output(ADD),
            ModelOutput.from_content("mockllm/model", content="sub done"),
            ModelOutput.from_content("mockllm/model", content="main done"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=h_sub_agent_turns_then_a_main_turn(),
        sentinel=[turn_escalated_to_human(), h_spy(seen)],
    )

    log = eval(task, model=model)[0]

    assert log.status == "success", log.error
    assert log.samples
    [turn] = [
        e
        for e in log.samples[0].events
        if isinstance(e, ModelEvent) and e.output.message.tool_calls
    ]
    assert turn.span_id == "sub-agent" and turn.uuid is not None
    approved = ("model_output", turn.uuid, ("c1",), "human", "proceed", None)
    assert [
        (s.conversation, s.subject, [kept(r) for r in s.decisions or ()]) for s in seen
    ] == [
        ("sub-agent", "Adding and shouting.", []),
        ("sub-agent", "sub done", [approved]),
        ("outer", "main done", []),
    ]


class Answered:
    """An event a test's panel sets once the person answers, made in the eval's loop."""

    def __init__(self) -> None:
        self._event: anyio.Event | None = None

    @property
    def event(self) -> anyio.Event:
        if self._event is None:
            self._event = anyio.Event()
        return self._event


def answer_by_call(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, ApprovalDecision]
) -> None:
    async def acp(**kwargs: object) -> Approval | None:
        return None

    async def panel(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: object,
        choices: list[str],
    ) -> Approval:
        return Approval(decision=answers[call.id], explanation="stop")

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    monkeypatch.setattr(approver_module, "panel_approval", panel)


def signal_when_recorded(
    monkeypatch: pytest.MonkeyPatch, factory: str, call_id: str, gate: Answered
) -> None:
    from inspect_ai._sentinel import _dispatch

    record = _dispatch._Recorder.record

    def recording(
        self: Any, context: Context, name: str, step: Any, reported: Any
    ) -> None:
        record(self, context, name, step, reported)
        if name == factory and getattr(step, "call", None) is not None:
            if step.call.id == call_id:
                gate.event.set()

    monkeypatch.setattr(_dispatch._Recorder, "record", recording)


@protocol
def h_holds(call_id: str, gate: Any) -> Protocol:
    async def decide(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.id == call_id:
            await gate.event.wait()
        return None

    return decide


@monitor
def h_opens(call_id: str, gate: Any) -> Monitor:
    async def check(context: Context, step: AfterToolCall) -> Observation | None:
        if step.call.id == call_id:
            gate.event.set()
        return None

    return check


def test_a_parallel_step_does_not_see_a_decision_before_its_step_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a_recorded, b_seen = Answered(), Answered()

    @tool(parallel=True)
    def gated() -> Tool:
        async def execute(x: int) -> str:
            """Return x once call A's answer is recorded.

            Args:
                x: A number.
            """
            await a_recorded.event.wait()
            return str(x)

        return execute

    answer_by_call(monkeypatch, {"A": "reject", "B": "approve"})
    signal_when_recorded(monkeypatch, "inspect_sentinel/human", "A", a_recorded)
    seen: list[Seen] = []
    calls = [
        ToolCall(id=id, function="gated", arguments={"x": x})
        for id, x in (("A", 1), ("B", 2))
    ]
    task = Task(
        dataset=[Sample(input="Run both.")],
        solver=[use_tools(gated()), generate()],
        # A's step stays open, its person's reject recorded, until B's
        # result has been seen
        sentinel=[
            h_ask("tool_call", ALL_CHOICES),
            h_holds("A", b_seen),
            h_spy(seen),
            h_opens("B", b_seen),
        ],
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            turn_output(*calls, content="Both at once."),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )

    log = eval(task, model=model)[0]

    assert log.status == "success", log.error
    assert log.samples
    assert sorted(
        (e.step_id, e.status, e.action)
        for e in log.samples[0].events
        if isinstance(e, SentinelEvent) and e.factory == "inspect_sentinel/human"
    ) == [
        ("A", "reported", "reject"),
        ("B", "reported", "proceed"),
    ]
    later = {
        (s.stage, s.subject): [
            (r.step_id, r.decided.report.action) for r in s.decisions or ()
        ]
        for s in seen
        if s.stage == "tool_result" or s.subject == "done"
    }
    assert later == {
        ("tool_result", "B"): [("B", "proceed")],
        ("model_output", "done"): [("B", "proceed"), ("A", "reject")],
    }


def test_a_closed_prompt_is_seen_later_by_its_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the person ends the prompt without choosing, and the host fails closed
    Panel("escalate", "closed the panel").install(monkeypatch)
    seen: list[Seen] = []

    log = run([escalated_to_human(), h_spy(seen)])

    assert log.status == "success", log.error
    [last] = [s for s in seen if s.subject == "done"]
    assert last.decisions is not None
    [record] = last.decisions
    assert record.decided.report.action == "reject"
    assert (record.decided.report.explanation or "").startswith(
        "The person closed the prompt without choosing; failing closed"
    )


@pytest.mark.parametrize(
    ("response", "explanation"),
    [
        # the person cancels the prompt: the client fails closed with reject,
        # which is offered by default, and says why
        (
            RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled")),
            "ACP client cancelled the permission request.",
        ),
        # the person selects reject: their own decision, with no reason typed
        (
            RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="reject")
            ),
            None,
        ),
    ],
)
def test_an_acp_cancellation_is_seen_later_by_its_explanation(
    monkeypatch: pytest.MonkeyPatch,
    response: RequestPermissionResponse,
    explanation: str | None,
) -> None:
    offered: list[list[str]] = []

    async def acp(**kwargs: Any) -> Approval | None:
        offered.append(list(kwargs["choices"]))
        return acp_module._approval_from_response(response, kwargs["choices"])

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    seen: list[Seen] = []

    log = run([escalated_to_human(), h_spy(seen)])

    assert log.status == "success", log.error
    assert offered == [["approve", "reject", "terminate"]]
    [last] = [s for s in seen if s.subject == "done"]
    assert last.decisions is not None
    [record] = last.decisions
    assert record.decided.report.action == "reject"
    assert record.decided.report.explanation == explanation
