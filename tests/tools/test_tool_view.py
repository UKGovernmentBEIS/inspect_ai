import io
import logging
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console
from test_helpers.tool_call_utils import get_tool_event
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.approval._apply import apply_tool_approval
from inspect_ai.approval._approval import Approval
from inspect_ai.approval._human.util import render_tool_approval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._call_tools import tool_call_view
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
    default_tool_call_viewer,
    resolve_tool_call_view,
)
from inspect_ai.tool._tool_def import ToolDef, tool_def_fields
from inspect_ai.tool._tools._execute import code_viewer
from inspect_ai.tool._tools._think import think_tool_viewer


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

    # the fallback is the default view, titled to say the viewer failed
    assert result is not None
    assert result.title is not None and "viewer" in result.title
    assert "failed" in result.title
    assert result.content == default_tool_call_viewer(call).call.content
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
    assert view.call.title is not None and "failed" in view.call.title


async def test_apply_tool_approval_rejects_when_viewer_raises() -> None:
    def raising_viewer(call: ToolCall) -> ToolCallView:
        raise TypeError("not a string")

    captured: dict[str, ToolCallView] = {}

    async def capture_approver(message, call, view, history) -> Approval:
        captured["view"] = view
        return Approval(decision="approve", explanation="ok")

    from inspect_ai.approval._apply import _tool_approver
    from inspect_ai.approval._policy import ApprovalPolicy, policy_approver

    token = _tool_approver.set(policy_approver([ApprovalPolicy(capture_approver, "*")]))
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


# Each closes a three-backtick fence, then opens an HTML comment, an HTML block
# or a heading, which would hide or relabel the lines after it.
_HIDING = [
    "ls\n```\n<!--\nrm -rf /tmp/data\n-->",
    "ls\n```\n<div>\n\nrm -rf /tmp/data\n</div>",
    "ls\n```\n# Approved\nrm -rf /tmp/data",
    "ls\n`````\n<!-- rm -rf /tmp/data",
]

# Legitimate code with backticks, which should read as written.
_BACKTICKS = [
    "echo `date`",
    "cat <<'EOF' > README.md\n```python\nprint('hi')\n```\nEOF",
]


def _render_approval(view: ToolCallView, arguments: dict[str, Any]) -> str:
    """The approval panel's text, as the console and Textual approvers show it."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, color_system=None)
    with patch("inspect_ai.approval._human.util.display_type", return_value="full"):
        for renderable in render_tool_approval("", view, arguments):
            console.print(renderable)
    return buffer.getvalue()


def _assert_shows_every_line(rendered: str, text: str) -> None:
    for line in text.splitlines():
        assert line.strip() in rendered, f"{line!r} is not shown"


@pytest.mark.parametrize("code", _HIDING + _BACKTICKS)
@pytest.mark.parametrize("language,param", [("bash", "command"), ("python", "code")])
def test_code_view_shows_every_line(code: str, language: str, param: str) -> None:
    call = ToolCall(id="1", function=language, arguments={param: code})
    view = code_viewer(language, param)(call)
    rendered = _render_approval(view, call.arguments)
    _assert_shows_every_line(rendered, code)
    # the view's own fence is not shown as text
    assert rendered.count("```") == code.count("```")


@pytest.mark.parametrize("value", _HIDING + _BACKTICKS)
def test_default_view_shows_every_argument(value: str) -> None:
    call = ToolCall(
        id="1", function="write_file", arguments={"path": "/tmp/x", "text": value}
    )
    view = default_tool_call_viewer(call)
    rendered = _render_approval(view, call.arguments)
    assert repr(value) in rendered
    assert "path='/tmp/x'" in rendered


def test_default_view_shows_strings_as_literals() -> None:
    # a quote in a string cannot make it read as two arguments
    call = ToolCall(id="1", function="f", arguments={"x": "a', y='b"})
    view = default_tool_call_viewer(call)
    rendered = _render_approval(view, call.arguments)
    assert """f(x="a', y='b")""" in rendered


@pytest.mark.parametrize("value", _HIDING + _BACKTICKS)
def test_agent_view_shows_every_line(value: str) -> None:
    from inspect_ai.agent._deepagent.agent_tool import agent_tool
    from inspect_ai.agent._deepagent.subagent import subagent

    viewer = tool_def_fields(
        agent_tool(
            subagents=[
                subagent(name="research", description="Research.", prompt="R."),
                subagent(name="general", description="General.", prompt="G."),
            ]
        )
    ).viewer
    assert viewer is not None
    arguments = {
        "subagent_type": "research",
        "task_description": f"Summarize\n{value}",
        "prompt": f"Read the repo.\n{value}\nThen report.",
    }
    view = viewer(ToolCall(id="1", function="agent", arguments=arguments))
    rendered = _render_approval(view, arguments)
    _assert_shows_every_line(rendered, arguments["task_description"])
    _assert_shows_every_line(rendered, arguments["prompt"])


# Notes a tool's own Markdown viewer puts outside any code block, each holding
# lines a Markdown renderer would not show: an HTML comment or block (with a
# reference definition inside), a reference definition, a link and an image.
_HIDDEN_IN_MARKDOWN = [
    "ok\n\n<!--\n\n[r]: /x\n\nrm -rf /tmp/data\n-->",
    "ok\n\n<div>\n[r]: /x\n\nrm -rf /tmp/data\n</div>",
    "ok\n\n[r]: /tmp/data\n\nrm -rf /tmp/data",
    "ok [see](rm -rf /tmp/data)",
    "ok <!-- rm -rf /tmp/data -->",
    "ok ![x](rm -rf /tmp/data)",
]


@pytest.mark.parametrize("notes", _HIDDEN_IN_MARKDOWN)
def test_approval_shows_hidden_markdown_text(notes: str) -> None:
    view = ToolCallView(
        call=ToolCallContent(format="markdown", content="Notes: {{notes}}")
    )
    rendered = _render_approval(view, {"notes": notes})
    _assert_shows_every_line(rendered, notes)


@pytest.mark.parametrize(
    "viewer,param",
    [
        (code_viewer("bash", "command"), "command"),
        (code_viewer("python", "code"), "code"),
        (think_tool_viewer(), "thought"),
    ],
)
def test_view_shows_placeholder_text_as_written(
    viewer: ToolCallViewer, param: str
) -> None:
    # the surfaces fill in `{{param}}` placeholders after the viewer runs, so
    # an argument holding one must be shown as written
    value = f"echo {{{{{param}}}}} {{{{other}}}}"
    arguments = {param: value, "other": "/etc/passwd"}
    view = viewer(ToolCall(id="1", function="tool", arguments=arguments))
    rendered = _render_approval(view, arguments)
    assert value in rendered
    assert "/etc/passwd" not in rendered


@pytest.mark.parametrize("viewer_fails", [False, True])
def test_default_view_shows_placeholder_text_as_written(viewer_fails: bool) -> None:
    arguments = {"text": "{{path}}", "path": "/tmp/x"}
    call = ToolCall(id="1", function="write", arguments=arguments)
    view = resolve_tool_call_view(call, _raising_viewer if viewer_fails else None)
    rendered = _render_approval(view, arguments)
    # a Python literal of the same string, not the path
    assert "text='{\\x7bpath}}'" in rendered
    assert rendered.count("/tmp/x") == 1


def _raising_viewer(call: ToolCall) -> ToolCallView:
    raise ValueError("bad")


@pytest.mark.parametrize("code", _HIDING)
def test_viewer_failure_view_shows_every_argument(code: str) -> None:
    def raising_viewer(call: ToolCall) -> ToolCallView:
        raise ValueError("bad")

    call = ToolCall(id="1", function="bash", arguments={"command": code})
    view = resolve_tool_call_view(call, raising_viewer)
    rendered = _render_approval(view, call.arguments)
    assert repr(code) in rendered
    assert "failed" in rendered
