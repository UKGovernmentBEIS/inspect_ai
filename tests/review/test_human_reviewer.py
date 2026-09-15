"""The human reviewer collects a review on the human approval surfaces."""

import pytest

from inspect_ai._util.registry import registry_lookup
from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._human import approver as human_module
from inspect_ai.model import ChatMessageTool
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.review import Review, human_reviewer
from inspect_ai.tool import ToolCallError
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView


class Surface:
    """Fakes the three surfaces: no ACP client, no panel, a scripted console."""

    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision
        self.views: list[ToolCallView] = []
        self.choices: list[list[str]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def acp(**kwargs: object) -> Approval | None:
            return None

        async def panel(*args: object, **kwargs: object) -> Approval:
            raise NotImplementedError

        def console(
            message: str, view: ToolCallView, choices: list[str], *args: object
        ) -> Approval:
            self.views.append(view)
            self.choices.append(choices)
            return Approval(decision=self.decision)

        monkeypatch.setattr(human_module, "request_human_approval_via_acp", acp)
        monkeypatch.setattr(human_module, "panel_approval", panel)
        monkeypatch.setattr(human_module, "console_approval", console)


def call() -> ToolCall:
    return ToolCall(id="c1", function="bash", arguments={"cmd": "curl example.com"})


def result(text: str = "HTTP/1.1 200 OK") -> ChatMessageTool:
    return ChatMessageTool(content=text, tool_call_id="c1", function="bash")


async def review(reviewer, view: ToolCallView | None = None) -> Review:
    history: list[ChatMessage] = []
    return await reviewer(
        "Fetching the page.", call(), result(), "", view or ToolCallView(), history
    )


@pytest.mark.parametrize(
    "surface_decision, review_decision",
    [("approve", "continue"), ("terminate", "terminate"), ("escalate", "escalate")],
)
async def test_the_operator_decision_becomes_a_review(
    monkeypatch: pytest.MonkeyPatch,
    surface_decision: ApprovalDecision,
    review_decision: str,
) -> None:
    surface = Surface(surface_decision)
    surface.install(monkeypatch)

    decided = await review(
        human_reviewer(choices=["continue", "terminate", "escalate"])
    )

    assert decided.decision == review_decision
    assert decided.explanation is not None
    assert surface.choices == [["approve", "terminate", "escalate"]]


async def test_the_operator_is_shown_the_call_and_its_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = Surface("approve")
    surface.install(monkeypatch)
    view = ToolCallView(call=ToolCallContent(format="text", content="curl example.com"))

    await review(human_reviewer(), view)

    [shown] = surface.views
    assert shown.call is not None
    assert "curl example.com" in shown.call.content
    assert "HTTP/1.1 200 OK" in shown.call.content


async def test_a_failed_call_shows_its_error(monkeypatch: pytest.MonkeyPatch) -> None:
    surface = Surface("approve")
    surface.install(monkeypatch)
    failed = ChatMessageTool(
        content="",
        tool_call_id="c1",
        function="bash",
        error=ToolCallError("timeout", "Command timed out"),
    )
    history: list[ChatMessage] = []

    await human_reviewer()("Fetching.", call(), failed, "", ToolCallView(), history)

    [shown] = surface.views
    assert shown.call is not None
    assert "Error (timeout): Command timed out" in shown.call.content


async def test_the_default_choices_are_continue_and_terminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = Surface("approve")
    surface.install(monkeypatch)

    await review(human_reviewer())

    assert surface.choices == [["approve", "terminate"]]


async def test_a_dismissed_request_terminates_the_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An ACP client dismissing the request reports `reject`, never offered.
    surface = Surface("reject")
    surface.install(monkeypatch)

    decided = await review(human_reviewer())

    assert decided.decision == "terminate"
    assert decided.explanation is not None
    assert "without one of the offered choices" in decided.explanation


async def test_an_acp_client_decision_is_used_when_one_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = Surface("approve")
    surface.install(monkeypatch)

    async def acp(**kwargs: object) -> Approval | None:
        return Approval(decision="terminate")

    monkeypatch.setattr(human_module, "request_human_approval_via_acp", acp)

    decided = await review(human_reviewer())

    assert decided.decision == "terminate"
    assert surface.views == []


async def test_the_operator_is_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from inspect_ai.util._notify import apprise_scope

    Surface("approve").install(monkeypatch)
    apprise = MagicMock()
    apprise.notify = MagicMock(return_value=True)

    with apprise_scope(apprise):
        await review(human_reviewer())

    apprise.notify.assert_called_once()
    assert apprise.notify.call_args.kwargs.get("body") == "Fetching the page."


async def test_backticks_in_the_result_cannot_close_its_code_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = Surface("approve")
    surface.install(monkeypatch)
    tricky = ChatMessageTool(
        content="```\n# not a heading\n```", tool_call_id="c1", function="bash"
    )
    history: list[ChatMessage] = []

    await human_reviewer()("Fetching.", call(), tricky, "", ToolCallView(), history)

    [shown] = surface.views
    assert shown.call is not None
    assert "````\n```\n# not a heading\n```\n````" in shown.call.content


async def test_placeholders_in_the_result_are_not_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.tool._tool_call import substitute_tool_call_content

    surface = Surface("approve")
    surface.install(monkeypatch)
    templated = ChatMessageTool(
        content="echo {{cmd}}", tool_call_id="c1", function="bash"
    )
    history: list[ChatMessage] = []

    await human_reviewer()("Fetching.", call(), templated, "", ToolCallView(), history)

    [shown] = surface.views
    assert shown.call is not None
    rendered = substitute_tool_call_content(shown.call, call().arguments)
    assert "curl example.com" not in rendered.content
    assert "echo { {cmd}}" in rendered.content


def test_the_human_reviewer_is_registered_by_name() -> None:
    assert registry_lookup("reviewer", "human") is not None


async def test_the_consoles_enter_default_cannot_continue_a_sample_it_was_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Against the real console surface, not a fake: rich returns the prompt's
    # default ("a", approve) on Enter whether or not approve is among the
    # choices, so a reviewer that does not offer `continue` relies on the
    # fail-closed mapping to stop the sample.
    from inspect_ai._display.core.active import clear_task_screen, init_task_screen
    from inspect_ai._display.core.display import TaskScreen

    async def no_acp(**kwargs: object) -> Approval | None:
        return None

    async def no_panel(*args: object, **kwargs: object) -> Approval:
        raise NotImplementedError

    monkeypatch.setattr(human_module, "request_human_approval_via_acp", no_acp)
    monkeypatch.setattr(human_module, "panel_approval", no_panel)
    monkeypatch.setattr("builtins.input", lambda *args: "")  # the operator hits Enter
    init_task_screen(TaskScreen())
    try:
        decided = await review(human_reviewer(choices=["terminate"]))
    finally:
        clear_task_screen()

    assert decided.decision == "terminate"


async def test_a_result_the_surfaces_cannot_render_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The surfaces render text only, and `ChatMessageTool.text` drops an
    # image: a screenshot-returning tool must not reach the operator looking
    # like a tool that returned nothing.
    from inspect_ai._util.content import ContentImage, ContentText

    surface = Surface("approve")
    surface.install(monkeypatch)
    shot = ChatMessageTool(
        content=[
            ContentText(text="clicked"),
            ContentImage(image="data:image/png;base64,iVBORw0KGgo="),
        ],
        tool_call_id="c1",
        function="computer",
    )
    history: list[ChatMessage] = []

    await human_reviewer()("Clicking.", call(), shot, "", ToolCallView(), history)

    [shown] = surface.views
    assert shown.call is not None
    assert "clicked\n[image]" in shown.call.content


async def test_a_text_view_stays_text_so_a_substituted_argument_cannot_forge_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The surfaces substitute `{{param}}` into the view after the reviewer
    # builds it, so a code fence sized at build time cannot contain what the
    # substitution puts inside it. Text stays text, which the panel and
    # console render without interpreting markdown at all.
    surface = Surface("approve")
    surface.install(monkeypatch)
    view = ToolCallView(call=ToolCallContent(format="text", content="run: {{cmd}}"))

    await review(human_reviewer(), view)

    [shown] = surface.views
    assert shown.call is not None
    assert shown.call.format == "text"
    assert "run: {{cmd}}" in shown.call.content
    assert "HTTP/1.1 200 OK" in shown.call.content
