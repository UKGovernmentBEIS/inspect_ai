import pytest

from inspect_ai import Task, eval
from inspect_ai.agent import as_solver, react
from inspect_ai.dataset import Sample
from inspect_ai.event._review import ReviewEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    ModelOutput,
    get_model,
)
from inspect_ai.review import Review, ReviewDecision, Reviewer, ReviewPolicy, reviewer
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
def recording_reviewer(
    seen: list[str], decision: ReviewDecision = "continue"
) -> Reviewer:
    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        seen.append(call.function)
        return Review(decision=decision)

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


@pytest.mark.parametrize("submit", [False, True])
@pytest.mark.parametrize("task_level", [False, True])
@pytest.mark.parametrize("matches", [False, True])
def test_react_replaces_and_restores_review_policies(
    submit: bool, task_level: bool, matches: bool
) -> None:
    scoped_seen: list[str] = []
    inherited_seen: list[str] = []
    inherited = [
        ReviewPolicy(recording_reviewer(inherited_seen, "terminate"), "addition")
    ]
    scoped = react(
        tools=[addition()],
        submit=submit,
        review=[
            ReviewPolicy(
                recording_reviewer(scoped_seen), "addition" if matches else "other"
            )
        ],
    )
    following = react(tools=[addition()], submit=False)
    call = ModelOutput.for_tool_call(
        "mockllm/model", tool_name="addition", tool_arguments={"x": 1, "y": 1}
    )
    answer = (
        ModelOutput.for_tool_call(
            "mockllm/model", tool_name="submit", tool_arguments={"answer": "2"}
        )
        if submit
        else ModelOutput.from_content("mockllm/model", content="2")
    )

    following_call = ModelOutput.for_tool_call(
        "mockllm/model", tool_name="addition", tool_arguments={"x": 2, "y": 2}
    )

    [log] = eval(
        Task(
            dataset=[Sample(input="What is 1 + 1?")],
            solver=[as_solver(scoped), as_solver(following)],
            review=inherited if task_level else None,
        ),
        model=get_model("mockllm/model", custom_outputs=[call, answer, following_call]),
        review=None if task_level else inherited,
    )

    assert log.status == "success"
    assert scoped_seen == (["addition"] if matches else [])
    assert inherited_seen == ["addition"]
    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, ReviewEvent)]
    assert [e.decision for e in events] == (
        ["continue", "terminate"] if matches else ["terminate"]
    )
    assert events[-1].call.arguments == {"x": 2, "y": 2}
