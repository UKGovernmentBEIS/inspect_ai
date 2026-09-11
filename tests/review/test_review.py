from pathlib import Path
from typing import NamedTuple

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.dataset import Sample
from inspect_ai.event._review import ReviewEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.log._log import EvalLog
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.review import (
    Review,
    ReviewDecision,
    Reviewer,
    ReviewPolicy,
    read_review_policies,
    review,
    reviewer,
)
from inspect_ai.review._policy import (
    ReviewerPolicyConfig,
    ReviewPolicyConfig,
    review_policies_from_config,
)
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool._tool import (
    Tool,
    ToolApprovalError,
    ToolParsingError,
    ToolResult,
    tool,
)
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_def import ToolDef


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
        return [ContentText(text=str(x + y))]

    return execute


@reviewer(name="fixed")
def fixed_reviewer(decision: ReviewDecision = "continue") -> Reviewer:
    async def review_(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        return Review(decision=decision, explanation="Fixed decision.")

    return review_


class Seen(NamedTuple):
    call: ToolCall
    result: ChatMessageTool
    output: ToolResult
    history: list[ChatMessage]


@reviewer
def recording_reviewer(seen: list[Seen]) -> Reviewer:
    async def review_(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        seen.append(Seen(call, result, output, list(history)))
        return Review(decision="continue")

    return review_


@reviewer
def generating_reviewer() -> Reviewer:
    async def review_(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        await get_model("mockllm/model").generate("Should this result stand?")
        return Review(decision="continue")

    return review_


@approver
def modifying_approver(x: int) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        modified = ToolCall(
            id=call.id, function=call.function, arguments={**call.arguments, "x": x}
        )
        return Approval(decision="modify", modified=modified)

    return approve


def policy(decision: ReviewDecision = "continue", tools: str = "*") -> ReviewPolicy:
    return ReviewPolicy(fixed_reviewer(decision), tools)


def addition_call(id: str = "test", x: int = 1, y: int = 1) -> ToolCall:
    return ToolCall(id=id, function="addition", arguments={"x": x, "y": y})


async def execute_addition(
    policies: list[ReviewPolicy],
    *calls: ToolCall,
    approval: list[ApprovalPolicy] | None = None,
    parallel: bool = False,
    max_output: int | None = None,
) -> list[ChatMessage]:
    init_transcript(Transcript())
    calls = calls or (addition_call(),)
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=list(calls))],
        [ToolDef(addition(), parallel=parallel)],
        max_output=max_output,
        approval=approval,
        review=policies,
    )
    return messages


def tool_message(messages: list[ChatMessage]) -> ChatMessageTool:
    return next(m for m in messages if isinstance(m, ChatMessageTool))


def review_events() -> list[ReviewEvent]:
    return [e for e in transcript().events if isinstance(e, ReviewEvent)]


def tool_events() -> list[ToolEvent]:
    return [e for e in transcript().events if isinstance(e, ToolEvent)]


# --- decisions ---------------------------------------------------------------


async def test_continue_passes_the_result_through() -> None:
    messages = await execute_addition([policy("continue")])

    assert tool_message(messages).content == [ContentText(text="2")]
    [event] = review_events()
    assert event.decision == "continue"
    assert event.reviewer == "fixed"


async def test_the_review_is_recorded_after_the_tool_event() -> None:
    await execute_addition([policy("continue")])

    events = transcript().events
    tool_index = next(i for i, e in enumerate(events) if isinstance(e, ToolEvent))
    review_index = next(i for i, e in enumerate(events) if isinstance(e, ReviewEvent))
    assert review_index > tool_index


async def test_terminate_ends_the_sample_after_recording_the_result() -> None:
    with pytest.raises(TerminateSampleError, match="reviewer requested termination"):
        await execute_addition([policy("terminate")])

    [event] = tool_events()
    assert event.pending is None
    assert event.result == [ContentText(text="2")]
    assert event.failed is True
    assert review_events()[-1].decision == "terminate"


async def test_terminate_with_a_parallel_sibling_finalises_both_events() -> None:
    with pytest.raises(TerminateSampleError):
        await execute_addition(
            [policy("terminate")],
            addition_call("a"),
            addition_call("b"),
            parallel=True,
        )

    events = tool_events()
    assert sorted(e.id for e in events) == ["a", "b"]
    assert all(e.pending is None for e in events)


@reviewer
def waiting_reviewer(
    started: anyio.Event,
    cleaned_up: anyio.Event,
    terminate_call: str | None = None,
) -> Reviewer:
    async def review_(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        if call.id == terminate_call:
            await started.wait()
            return Review(decision="terminate")
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            cleaned_up.set()
        return Review(decision="continue")

    return review_


async def test_operator_cancel_during_review_terminates_and_preserves_result() -> None:
    init_transcript(Transcript())
    started = anyio.Event()
    cleaned_up = anyio.Event()

    async def cancel_review() -> None:
        await started.wait()
        [event] = tool_events()
        event._cancel()

    async with anyio.create_task_group() as tg:
        tg.start_soon(cancel_review)
        with pytest.raises(TerminateSampleError, match="review.*cancelled"):
            await execute_tools(
                [ChatMessageAssistant(content=[], tool_calls=[addition_call()])],
                [addition()],
                review=[ReviewPolicy(waiting_reviewer(started, cleaned_up), "*")],
            )

    [event] = tool_events()
    assert event.result == [ContentText(text="2")]
    assert event.error is None
    assert event.pending is None
    assert event.completed is not None
    assert cleaned_up.is_set()
    assert review_events() == []


async def test_sibling_termination_during_review_preserves_completed_result() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()
    with pytest.raises(TerminateSampleError, match="reviewer requested termination"):
        await execute_addition(
            [ReviewPolicy(waiting_reviewer(started, cleaned_up, "a"), "*")],
            addition_call("a"),
            addition_call("b", x=3),
            parallel=True,
        )

    events = {event.id: event for event in tool_events()}
    assert events["b"].result == [ContentText(text="4")]
    assert events["b"].error is None
    assert all(event.pending is None for event in events.values())
    assert cleaned_up.is_set()
    assert [(event.call.id, event.decision) for event in review_events()] == [
        ("a", "terminate")
    ]


async def test_sample_cancellation_during_review_preserves_completed_result() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()

    with anyio.CancelScope() as scope:

        async def cancel_sample() -> None:
            await started.wait()
            scope.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(cancel_sample)
            await execute_addition(
                [ReviewPolicy(waiting_reviewer(started, cleaned_up), "*")]
            )

    assert scope.cancelled_caught
    [event] = tool_events()
    assert event.result == [ContentText(text="2")]
    assert event.error is None
    assert event.pending is None
    assert cleaned_up.is_set()
    assert review_events() == []


async def test_escalate_falls_through_to_the_next_reviewer() -> None:
    messages = await execute_addition([policy("escalate"), policy("continue")])

    assert tool_message(messages).error is None
    assert [e.decision for e in review_events()] == ["escalate", "continue"]


async def test_an_escalation_nobody_takes_continues_and_is_recorded() -> None:
    messages = await execute_addition([policy("escalate")])

    assert tool_message(messages).error is None
    assert [(e.reviewer, e.decision) for e in review_events()] == [
        ("fixed", "escalate"),
        ("policy", "continue"),
    ]


async def test_a_result_no_policy_covers_continues_without_review() -> None:
    messages = await execute_addition([policy("terminate", tools="foo*")])

    assert tool_message(messages).content == [ContentText(text="2")]
    assert review_events() == []


# --- what the reviewer sees ----------------------------------------------------


async def test_the_reviewer_sees_the_call_the_result_the_output_and_the_history() -> (
    None
):
    seen: list[Seen] = []

    await execute_addition([ReviewPolicy(recording_reviewer(seen), "*")])

    [one] = seen
    assert one.call.id == "test"
    assert one.result.tool_call_id == "test"
    assert one.result.content == [ContentText(text="2")]
    assert one.output == [ContentText(text="2")]
    assert isinstance(one.history[-1], ChatMessageAssistant)
    assert one.history[-1].tool_calls == [one.call]


async def test_the_reviewer_sees_the_call_as_modified_by_an_approver() -> None:
    seen: list[Seen] = []

    messages = await execute_addition(
        [ReviewPolicy(recording_reviewer(seen), "*")],
        approval=[ApprovalPolicy(modifying_approver(5), "*")],
    )

    assert tool_message(messages).content == [ContentText(text="6")]
    assert seen[0].call.arguments == {"x": 5, "y": 1}


async def test_the_reviewer_sees_the_modified_call_when_the_tool_raises() -> None:
    from inspect_ai.tool._tool import ToolError

    @tool
    def failing():
        async def execute(x: int) -> str:
            """Always fail.

            Args:
                x: A number.
            """
            raise ToolError(f"boom with x={x}")

        return execute

    seen: list[Seen] = []
    init_transcript(Transcript())
    call = ToolCall(id="f", function="failing", arguments={"x": 1})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [ToolDef(failing())],
        approval=[ApprovalPolicy(modifying_approver(99), "*")],
        review=[ReviewPolicy(recording_reviewer(seen), "*")],
    )

    [one] = seen
    assert one.call.arguments == {"x": 99}
    assert one.result.error is not None
    assert "x=99" in one.result.error.message
    assert tool_message(messages).error is not None


async def test_the_reviewer_sees_the_untruncated_output() -> None:
    @tool
    def verbose():
        async def execute() -> str:
            """Return a long string."""
            return "x" * 500

        return execute

    seen: list[Seen] = []
    init_transcript(Transcript())
    call = ToolCall(id="v", function="verbose", arguments={})
    messages, _ = await execute_tools(
        [ChatMessageAssistant(content=[], tool_calls=[call])],
        [ToolDef(verbose())],
        max_output=100,
        review=[ReviewPolicy(recording_reviewer(seen), "*")],
    )

    [one] = seen
    assert one.output == "x" * 500
    assert len(tool_message(messages).text) < 500
    assert one.result.text == tool_message(messages).text


async def test_calls_that_never_executed_are_not_reviewed() -> None:
    seen: list[Seen] = []

    messages = await execute_addition(
        [ReviewPolicy(recording_reviewer(seen), "*")],
        ToolCall(id="test", function="nonexistent", arguments={}),
    )

    assert seen == []
    error = tool_message(messages).error
    assert error is not None
    assert error.type == "parsing"


@pytest.mark.parametrize(
    "error",
    [
        ToolParsingError("The tool reported a parsing error."),
        ToolApprovalError("The tool reported an approval error."),
        ValueError("embedded null byte"),
    ],
)
async def test_errors_from_executed_tools_are_reviewed(error: Exception) -> None:
    executed: list[bool] = []

    @tool
    def failing() -> Tool:
        async def execute() -> str:
            """Run a tool that reports an error."""
            executed.append(True)
            raise error

        return execute

    seen: list[Seen] = []
    init_transcript(Transcript())
    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content=[],
                tool_calls=[ToolCall(id="f", function="failing", arguments={})],
            )
        ],
        [failing()],
        review=[ReviewPolicy(recording_reviewer(seen), "*")],
    )

    assert executed == [True]
    [one] = seen
    assert one.result.error is not None
    assert one.result.error == tool_message(messages).error
    assert one.output == ""
    assert review_events()[0].call.id == "f"


@pytest.mark.parametrize(
    "call",
    [
        ToolCall(id="test", function="addition", arguments={}),
        ToolCall(
            id="test", function="addition", arguments={"x": "not a number", "y": 1}
        ),
        ToolCall(
            id="test", function="addition", arguments={}, parse_error="Invalid JSON"
        ),
    ],
)
async def test_argument_validation_failures_are_not_reviewed(call: ToolCall) -> None:
    seen: list[Seen] = []
    messages = await execute_addition(
        [ReviewPolicy(recording_reviewer(seen), "*")], call
    )

    assert seen == []
    error = tool_message(messages).error
    assert error is not None
    assert error.type == "parsing"


async def test_approval_rejections_are_not_reviewed() -> None:
    @approver
    def rejecting_approver() -> Approver:
        async def approve(
            message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
        ) -> Approval:
            return Approval(decision="reject")

        return approve

    seen: list[Seen] = []
    messages = await execute_addition(
        [ReviewPolicy(recording_reviewer(seen), "*")],
        approval=[ApprovalPolicy(rejecting_approver(), "*")],
    )

    assert seen == []
    error = tool_message(messages).error
    assert error is not None
    assert error.type == "approval"


async def test_handoffs_are_not_reviewed() -> None:
    from inspect_ai.agent import Agent, AgentState, agent, handoff

    @agent
    def helper() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            state.messages.append(ChatMessageAssistant(content="helper says hi"))
            return state

        return execute

    seen: list[Seen] = []
    init_transcript(Transcript())
    messages, _ = await execute_tools(
        [
            ChatMessageAssistant(
                content=[],
                tool_calls=[
                    ToolCall(id="test", function="transfer_to_helper", arguments={})
                ],
            )
        ],
        [handoff(helper(), description="A helper agent.")],
        review=[ReviewPolicy(recording_reviewer(seen), "*")],
    )

    assert seen == []
    assert any("helper says hi" in m.text for m in messages)


async def test_reviewer_inference_is_exempt_from_limits() -> None:
    from inspect_ai.util._limit import token_limit, turn_limit

    with token_limit(1_000_000) as tokens, turn_limit(10) as turns:
        messages = await execute_addition([ReviewPolicy(generating_reviewer(), "*")])

    assert tool_message(messages).error is None
    assert tokens.usage == 0
    assert turns.usage == 0


# --- configuration -----------------------------------------------------------


def test_review_context_manager_sets_and_restores() -> None:
    from inspect_ai.review._apply import _tool_reviewer

    assert _tool_reviewer.get(None) is None
    with review([policy()]):
        outer = _tool_reviewer.get(None)
        assert outer is not None
        with review([policy("terminate")]):
            assert _tool_reviewer.get(None) is not outer
        assert _tool_reviewer.get(None) is outer
    assert _tool_reviewer.get(None) is None


def review_model() -> Model:
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                tool_name="addition",
                tool_arguments={"x": 1, "y": 1},
            ),
            ModelOutput.from_content("mockllm/model", content="2"),
        ],
        memoize=False,
    )


def review_task(task_review=None) -> Task:
    return Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=[use_tools(addition()), generate()],
        scorer=match(numeric=True),
        review=task_review,
    )


def review_yaml() -> str:
    return (Path(__file__).parent / "continue.yaml").as_posix()


def log_review_events(log: EvalLog) -> list[ReviewEvent]:
    assert log.samples
    return [e for e in log.samples[0].events if isinstance(e, ReviewEvent)]


def test_task_level_review_runs_and_is_recorded_in_config() -> None:
    [log] = eval(review_task([policy("continue")]), model=review_model())

    assert [e.decision for e in log_review_events(log)] == ["continue"]
    assert log.eval.config.review == ReviewPolicyConfig(
        reviewers=[
            ReviewerPolicyConfig(
                name="fixed", tools="*", params={"decision": "continue"}
            )
        ]
    )


def test_eval_level_review_takes_precedence() -> None:
    [log] = eval(
        review_task([policy("continue")]),
        model=review_model(),
        review=[policy("terminate")],
    )

    assert log.samples
    assert log.samples[0].limit is not None
    assert log.samples[0].limit.type == "operator"
    assert log_review_events(log)[-1].decision == "terminate"
    assert log.eval.config.review is not None
    assert log.eval.config.review.reviewers[0].params == {"decision": "terminate"}


def test_review_config_file() -> None:
    [log] = eval(review_task(review_yaml()), model=review_model())

    assert [e.decision for e in log_review_events(log)] == ["continue"]


def test_read_review_policies_file() -> None:
    policies = read_review_policies(review_yaml())

    assert [p.tools for p in policies] == ["foo*", "*"]


def test_review_policies_from_config_object() -> None:
    config = ReviewPolicyConfig.model_validate(
        {"reviewers": [{"name": "fixed", "tools": "*", "decision": "escalate"}]}
    )

    [only] = review_policies_from_config(config)

    assert only.tools == "*"
    assert callable(only.reviewer)
