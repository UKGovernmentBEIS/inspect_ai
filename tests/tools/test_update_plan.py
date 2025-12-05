"""Tests for update_plan tool."""

import pytest
from test_helpers.tool_call_utils import get_tool_event

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import update_plan


@pytest.mark.asyncio
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
