from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event._review import ReviewEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    ModelOutput,
    get_model,
)
from inspect_ai.review import Review, Reviewer, ReviewPolicy, reviewer
from inspect_ai.tool import ToolCall, ToolCallView, ToolResult, tool


@tool
def addition():
    async def execute(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return execute


@reviewer
def recording_reviewer(seen: list[str]) -> Reviewer:
    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        seen.append(call.function)
        return Review(decision="continue")

    return review


def addition_then_answer():
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="addition", tool_arguments={"x": 1, "y": 1}
            ),
            ModelOutput.from_content("mockllm/model", content="2"),
        ],
    )


def test_react_scopes_review_policies_to_the_agent() -> None:
    seen: list[str] = []
    agent = react(
        tools=[addition()],
        submit=False,
        review=[ReviewPolicy(recording_reviewer(seen), "addition")],
    )

    [log] = eval(
        Task(dataset=[Sample(input="What is 1 + 1?")], solver=agent),
        model=addition_then_answer(),
    )

    assert log.status == "success"
    assert seen == ["addition"]
    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, ReviewEvent)]
    assert [e.decision for e in events] == ["continue"]
