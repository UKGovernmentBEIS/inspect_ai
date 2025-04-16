import pytest

from inspect_ai import Task, eval
from inspect_ai.model import ChatMessage, ChatMessageTool, Model, ModelOutput, get_model
from inspect_ai.solver import Generate, TaskState, generate, solver, use_tools
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import subtask


@pytest.mark.anyio
async def test_model_tool_error():
    """Test that ToolError is caught when running under both asyncio and trio."""
    model = tool_calling_model()
    messages, _ = await model.generate_loop(
        "Please call the unreliable tool", tools=[unreliable()]
    )
    check_tool_message(messages[1])


def test_task_tool_error():
    """Test that ToolError is caught in a normal task."""
    task = Task(
        solver=[use_tools(unreliable()), generate()],
    )
    log = eval(task, model=tool_calling_model())[0]
    assert log.status == "success"
    assert log.samples
    check_tool_message(log.samples[0].messages[2])


def test_subtask_tool_error():
    """Test that ToolError is caught in a subtask."""

    @subtask
    async def my_subtask() -> None:
        model = tool_calling_model()
        messages, _ = await model.generate_loop(
            "Please call the unreliable tool", tools=[unreliable()]
        )
        check_tool_message(messages[1])

    @solver
    def subtask_solver():
        async def solve(state: TaskState, generate: Generate):
            await my_subtask()
            return state

        return solve

    task = Task(solver=subtask_solver())
    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"


def check_tool_message(message: ChatMessage) -> None:
    assert isinstance(message, ChatMessageTool)
    assert message.error is not None
    assert message.error.message == UNRELIABLE_TOOL_ERROR


UNRELIABLE_TOOL_ERROR = "Error occurred while processing."


@tool
def unreliable():
    async def execute():
        """
        Take an unreliable action.

        Returns:
            A string with the word "unreliable"
        """
        raise ToolError(UNRELIABLE_TOOL_ERROR)

        return "unreliable"

    return execute


def tool_calling_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "unreliable", {}),
            ModelOutput.from_content("mockllm/model", "That tools seems unreliable."),
        ],
    )
