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
from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
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


def _render_approval(
    view: ToolCallView, arguments: dict[str, Any], call: ToolCall | None = None
) -> str:
    """The approval panel's text, as the console and Textual approvers show it."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, color_system=None)
    with patch("inspect_ai.approval._human.util.display_type", return_value="full"):
        for renderable in render_tool_approval("", view, arguments, call):
            console.print(renderable)
    return buffer.getvalue()


def _agent_viewer() -> ToolCallViewer:
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
    return viewer


@pytest.mark.parametrize("code", _HIDING + _BACKTICKS)
@pytest.mark.parametrize(
    "viewer,param",
    [
        (code_viewer("bash", "command"), "command"),
        (code_viewer("python", "code"), "code"),
        (think_tool_viewer(), "thought"),
        (_agent_viewer(), "prompt"),
    ],
)
def test_approval_of_an_inspect_view_shows_every_argument(
    code: str, viewer: ToolCallViewer, param: str
) -> None:
    # the tool's own view can hide lines; the full tool call block shows them all
    call = ToolCall(id="1", function="tool", arguments={param: code})
    rendered = _render_approval(viewer(call), call.arguments, call)
    assert "Full tool call" in rendered
    assert f"tool({param}={code!r})" in rendered


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


def test_default_view_shows_argument_names_literally() -> None:
    # an argument name that is not an identifier cannot read as other arguments
    arguments = {"path": "/srv/data", "dry_run=True, unused": False}
    call = ToolCall(id="1", function="remove", arguments=arguments)
    rendered = _render_approval(default_tool_call_viewer(call), arguments)
    assert "remove(path='/srv/data', **{'dry_run=True, unused': False})" in rendered


@pytest.mark.parametrize(
    "name",
    [
        "path",
        "café",  # a non-ASCII name normalization leaves as it is
        "dry_run\u034f",  # an invisible combining grapheme joiner
        "dry_run=True, unused",
        "class",
        "\U0001d68d\U0001d69b\U0001d6a2_run",  # mathematical monospace "dry"
        "\uff44ry_run",  # full-width "d"
        "\u212a",  # Kelvin sign, read as "K"
    ],
)
def test_default_view_reads_as_the_call_it_shows(name: str) -> None:
    import ast

    arguments = {"path": "/srv/data", name: False}
    call = ToolCall(id="1", function="remove", arguments=arguments)
    view = default_tool_call_viewer(call).call
    assert view is not None
    code = view.content.strip().split("\n")[1:-1]
    shown = ast.parse("\n".join(code), mode="eval").body
    assert isinstance(shown, ast.Call)
    read: dict[str, Any] = {}
    for keyword in shown.keywords:
        value = ast.literal_eval(keyword.value)
        if keyword.arg is None:
            read.update(value)
        else:
            read[keyword.arg] = value
    assert read == arguments


def test_default_view_escapes_names_other_than_ascii_identifiers() -> None:
    # a name with an invisible mark reads as the name without it
    arguments = {"dry_run\u034f": True, "path": "/data"}
    call = ToolCall(id="1", function="remove", arguments=arguments)
    rendered = _render_approval(default_tool_call_viewer(call), arguments)
    assert "remove(path='/data', **{'dry_run\\u034f': True})" in rendered
    assert "\u034f" not in rendered


@pytest.mark.parametrize(
    "invisible",
    ["\u034f", "\ufe0f", "\U000e0100", "\u115f", "\u1160", "\u3164", "\uffa0"],
)
def test_default_view_escapes_invisible_characters_in_strings(
    invisible: str,
) -> None:
    import ast

    value = f"rm{invisible} -rf /data"
    arguments = {"cmd": value, "options": [{"name": f"a{invisible}"}]}
    call = ToolCall(id="1", function="run", arguments=arguments)
    view = default_tool_call_viewer(call).call
    assert view is not None
    assert invisible not in view.content
    code = "\n".join(view.content.strip().split("\n")[1:-1])
    shown = ast.parse(code, mode="eval").body
    assert isinstance(shown, ast.Call)
    read = {k.arg: ast.literal_eval(k.value) for k in shown.keywords}
    assert read == arguments


def test_default_view_leaves_visible_combining_marks() -> None:
    # e + combining acute accent renders as é
    call = ToolCall(id="1", function="f", arguments={"x": "cafe\u0301"})
    view = default_tool_call_viewer(call).call
    assert view is not None
    assert "x='cafe\u0301'" in view.content


def test_approval_shows_arguments_beneath_a_custom_view() -> None:
    # a tool's own Markdown view that a renderer shows only part of
    notes = "ok\n\n<!--\nrm -rf /tmp/data\n-->"
    call = ToolCall(id="1", function="note", arguments={"notes": notes})
    view = ToolCallView(
        call=ToolCallContent(format="markdown", content="Notes: {{notes}}")
    )
    rendered = _render_approval(view, call.arguments, call)
    assert "Full tool call" in rendered
    assert f"note(notes={notes!r})" in rendered


def _first_line_only(view: ToolCallView, edit: str) -> ToolCallView:
    # a custom viewer that cuts a built-in view down to the command's first line
    assert view.call is not None
    first = view.call.content.split("\n")[:2]
    content = "\n".join([*first, "```"])
    if edit == "copy":
        return ToolCallView(call=view.call.model_copy(update={"content": content}))
    view.call.content = content
    return view


@pytest.mark.parametrize("edit", ["copy", "assign"])
@pytest.mark.parametrize("builtin", ["bash", "default"])
def test_approval_shows_arguments_beneath_an_edited_inspect_view(
    edit: str, builtin: str
) -> None:
    call = ToolCall(
        id="1", function="bash", arguments={"command": "ls\nrm -rf /tmp/data"}
    )
    view = (
        tool_def_fields(bash()).viewer
        if builtin == "bash"
        else default_tool_call_viewer
    )
    assert view is not None
    edited = _first_line_only(view(call), edit)
    rendered = _render_approval(edited, call.arguments, call)
    assert "Full tool call" in rendered
    assert "rm -rf /tmp/data" in rendered


@pytest.mark.parametrize("viewer_fails", [False, True])
def test_approval_shows_no_arguments_block_beneath_the_default_view(
    viewer_fails: bool,
) -> None:
    call = ToolCall(id="1", function="tool", arguments={"path": "/tmp/x"})
    view = resolve_tool_call_view(call, _raising_viewer if viewer_fails else None)
    assert "Full tool call" not in _render_approval(view, call.arguments, call)


def test_default_view_equals_its_round_trip() -> None:
    # nothing but the view's fields is kept on it, so a message holding it
    # compares equal after serialization (bridge filters rely on this)
    call = ToolCall(id="1", function="tool", arguments={"path": "/tmp/x"})
    call.view = default_tool_call_viewer(call).call
    message = ChatMessageAssistant(content="", tool_calls=[call])
    assert ChatMessageAssistant.model_validate(message.model_dump()) == message


@pytest.mark.parametrize(
    "viewer,param",
    [
        (code_viewer("bash", "command"), "command"),
        (code_viewer("python", "code"), "code"),
        (think_tool_viewer(), "thought"),
    ],
)
def test_approval_shows_placeholder_text_as_written(
    viewer: ToolCallViewer, param: str
) -> None:
    # the surfaces fill in `{{param}}` placeholders in a view, so the arguments
    # block shows an argument holding one as written
    value = f"echo {{{{{param}}}}} {{{{other}}}}"
    arguments = {param: value, "other": "/etc/passwd"}
    call = ToolCall(id="1", function="tool", arguments=arguments)
    rendered = _render_approval(viewer(call), arguments, call)
    assert f"{param}='echo {{\\x7b{param}}}}} {{\\x7bother}}}}'" in rendered


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
