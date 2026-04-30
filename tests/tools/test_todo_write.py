"""Tests for todo_write tool."""

from test_helpers.tool_call_utils import get_tool_event

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import todo_write


async def test_todo_write_basic() -> None:
    """Test basic todo write."""
    tool = todo_write()
    result = await tool(
        todos=[
            {"content": "Step 1", "status": "completed"},
            {"content": "Step 2", "status": "in_progress"},
            {"content": "Step 3", "status": "pending"},
        ],
        explanation="Making progress",
    )
    assert result == "Plan updated"


def test_todo_write_via_mockllm() -> None:
    """Test todo_write through a mocked model evaluation."""
    task = Task(
        dataset=[Sample(input="Create a plan")],
        solver=[use_tools(todo_write()), generate()],
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="todo_write",
                tool_arguments={
                    "todos": [
                        {"content": "Analyze", "status": "in_progress"},
                        {"content": "Implement", "status": "pending"},
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
    assert tool_event.function == "todo_write"
    assert isinstance(tool_event.arguments["todos"], list)
    assert len(tool_event.arguments["todos"]) == 2
