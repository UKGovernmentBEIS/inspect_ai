"""Tests for update_plan tool."""

import json

from test_helpers.tool_call_utils import get_tool_event

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._openai_responses import _responses_call_to_inspect
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import ToolInfo, update_plan
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._todo_write import todo_write


def _todo_write_tool_info() -> ToolInfo:
    # the swap only engages for a tool whose schema matches canonical todo_write()
    td = ToolDef(todo_write())
    return ToolInfo(name=td.name, description=td.description, parameters=td.parameters)


async def test_update_plan_basic() -> None:
    """Test basic plan update."""
    tool = update_plan()
    result = await tool(
        plan=[
            {"step": "Step 1", "status": "completed"},
            {"step": "Step 2", "status": "in_progress"},
            {"step": "Step 3", "status": "pending"},
        ],
        explanation="Making progress",
    )
    assert result == "Plan updated"


def test_update_plan_args_mapped_when_trailed_by_stray_quotes() -> None:
    # parse_tool_call() recovers a complete object trailed by stray quotes, so the
    # plan->todos mapping has to run on it too, or the recovered call arrives with
    # update_plan's shape under todo_write's name
    name, arguments = _responses_call_to_inspect(
        "update_plan",
        '{"plan": [{"step": "Analyze", "status": "pending"}]}""',
        [_todo_write_tool_info()],
    )

    assert name == "todo_write"
    assert json.loads(arguments) == {
        "todos": [{"content": "Analyze", "status": "pending"}]
    }


def test_update_plan_args_passed_through_when_unrecoverable() -> None:
    # arguments that stay malformed are still handed over untouched so that
    # parse_tool_call() reports the parse error
    malformed = '{"plan": [{"step": "Analyze"'
    name, arguments = _responses_call_to_inspect(
        "update_plan", malformed, [_todo_write_tool_info()]
    )

    assert name == "todo_write"
    assert arguments == malformed


def test_update_plan_via_mockllm() -> None:
    """Test update_plan through a mocked model evaluation."""
    task = Task(
        dataset=[Sample(input="Create a plan")],
        solver=[use_tools(update_plan()), generate()],
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="update_plan",
                tool_arguments={
                    "plan": [
                        {"step": "Analyze", "status": "in_progress"},
                        {"step": "Implement", "status": "pending"},
                    ]
                },
            ),
            ModelOutput.from_content("mockllm/model", "Done"),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    tool_event = get_tool_event(log)
    assert tool_event is not None
    assert tool_event.function == "update_plan"
    assert isinstance(tool_event.arguments["plan"], list)
    assert len(tool_event.arguments["plan"]) == 2
