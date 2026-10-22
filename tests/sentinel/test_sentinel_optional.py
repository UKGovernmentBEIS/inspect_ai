import sys

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import Tool, tool


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


def test_eval_with_tool_calls_runs_without_inspect_sentinel() -> None:
    assert sys.modules["inspect_sentinel"] is None
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "addition", {"x": 1, "y": 2}),
            ModelOutput.from_content("mockllm/model", content="3"),
        ],
        memoize=False,
    )
    task = Task(
        dataset=[Sample(input="What is 1 + 2?")],
        solver=[use_tools(addition()), generate()],
    )
    log = eval(task, model=model, display="none")[0]
    assert log.status == "success", log.error
    assert log.samples is not None
    assert [m.text for m in log.samples[0].messages if m.role == "tool"] == ["3"]
