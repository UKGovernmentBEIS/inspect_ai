import logging

import pytest
from test_helpers.tool_call_utils import get_tool_event
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.approval._apply import apply_tool_approval
from inspect_ai.approval._approval import Approval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._call_tools import tool_call_view
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    resolve_tool_call_view,
)
from inspect_ai.tool._tool_def import ToolDef


@skip_if_no_docker
@pytest.mark.slow
def test_tool_view():
    task = Task(
        dataset=[
            Sample(
                input="Please use the bash tool to list the files in the current directory?"
            )
        ],
        solver=[use_tools(bash()), generate()],
        sandbox="docker",
    )
    log = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="bash",
                    tool_arguments={"code": "ls ."},
                ),
                ModelOutput.from_content(model="mockllm/model", content="All done!."),
            ],
        ),
    )[0]

    event = get_tool_event(log)
    assert event.view is not None


def _make_tool_def(name: str, viewer) -> ToolDef:
    async def execute(thought: str) -> str:
        return ""

    return ToolDef(
        execute,
        name=name,
        description="test",
        parameters={"thought": "a thought"},
        viewer=viewer,
    )


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _attach(logger_name: str) -> _ListHandler:
    handler = _ListHandler()
    logging.getLogger(logger_name).addHandler(handler)
    return handler


def test_tool_call_view_swallows_viewer_error():
    def raising_viewer(call: ToolCall) -> ToolCallView:
        return ToolCallView(
            call=ToolCallContent(
                format="markdown", content=call.arguments["missing_key"]
            )
        )

    tdef = _make_tool_def("viewer_keyerror_tool", raising_viewer)
    call = ToolCall(id="1", function="viewer_keyerror_tool", arguments={})

    handler = _attach("inspect_ai.model._call_tools")
    try:
        result = tool_call_view(call, [tdef])
    finally:
        logging.getLogger("inspect_ai.model._call_tools").removeHandler(handler)

    assert result is None
    assert any(
        "viewer_keyerror_tool" in r.getMessage() and "Error in viewer" in r.getMessage()
        for r in handler.records
    )


def test_tool_call_view_returns_view_when_viewer_succeeds():
    def good_viewer(call: ToolCall) -> ToolCallView:
        return ToolCallView(
            call=ToolCallContent(format="markdown", content="rendered ok")
        )

    tdef = _make_tool_def("viewer_ok_tool", good_viewer)
    call = ToolCall(id="1", function="viewer_ok_tool", arguments={})

    result = tool_call_view(call, [tdef])

    assert result is not None
    assert result.content == "rendered ok"


def test_resolve_tool_call_view_falls_back_when_viewer_raises() -> None:
    def raising_viewer(call: ToolCall) -> ToolCallView:
        raise TypeError("not a string")

    # the default mode, used after the call has run (after-tool sentinel,
    # tool result review), keeps the default rendering
    call = ToolCall(id="1", function="viewer_fallback_tool", arguments={"x": 1})
    view = resolve_tool_call_view(call, raising_viewer)
    assert view.call is not None
    assert "viewer_fallback_tool" in view.call.content


async def test_apply_tool_approval_rejects_when_viewer_raises() -> None:
    def raising_viewer(call: ToolCall) -> ToolCallView:
        raise TypeError("not a string")

    captured: dict[str, ToolCallView] = {}

    async def capture_approver(message, call, view, history) -> Approval:
        captured["view"] = view
        return Approval(decision="approve", explanation="ok")

    from inspect_ai.approval._apply import _tool_approver

    token = _tool_approver.set(capture_approver)
    handler = _attach("inspect_ai.tool._tool_call")
    try:
        approved, approval = await apply_tool_approval(
            "msg",
            ToolCall(id="1", function="viewer_typeerror_tool", arguments={"x": 1}),
            raising_viewer,
            [],
        )
    finally:
        _tool_approver.reset(token)
        logging.getLogger("inspect_ai.tool._tool_call").removeHandler(handler)

    # the approver is not asked to decide on a fallback rendering
    assert approved is False
    assert captured == {}
    assert approval is not None
    assert approval.decision == "reject"
    assert approval.explanation is not None
    assert "viewer for tool 'viewer_typeerror_tool' failed" in approval.explanation
    assert "not a string" in approval.explanation
    assert any(
        "viewer_typeerror_tool" in r.getMessage()
        and "Error in viewer" in r.getMessage()
        for r in handler.records
    )


async def test_generate_views_the_call_as_the_model_gave_it() -> None:
    """The generation-time view renders the model's call without validating it."""
    viewed: list[dict[str, object]] = []

    def viewer(call: ToolCall) -> ToolCallView:
        viewed.append(call.arguments)
        return ToolCallView(call=ToolCallContent(format="text", content="viewed"))

    tdef = _make_tool_def("viewer_unvalidated_tool", viewer)
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name=tdef.name, tool_arguments={"thought": 5}
            )
        ],
    )
    output = await model.generate("go", tools=[tdef])

    assert output.message.tool_calls
    view = output.message.tool_calls[0].view
    assert view is not None and view.content == "viewed"
    assert viewed == [{"thought": 5}]
