"""Review policies grouped into chains: every covering chain runs, terminate wins."""

import anyio

from inspect_ai.event._review import ReviewEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import ChatMessage, ChatMessageTool
from inspect_ai.review import Review, ReviewDecision, Reviewer, ReviewPolicy, reviewer
from inspect_ai.review._policy import (
    config_from_review_policies,
    policy_reviewer,
    review_policies_from_config,
)
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallView


@reviewer(name="fixed")
def fixed_reviewer(decision: ReviewDecision = "continue") -> Reviewer:
    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        return Review(decision=decision, explanation=f"fixed {decision}")

    return review


@reviewer
def recording_reviewer(seen: list[ToolCallView]) -> Reviewer:
    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        seen.append(view)
        return Review(decision="continue")

    return review


@reviewer
def waiting_reviewer(cleaned_up: anyio.Event) -> Reviewer:
    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        try:
            await anyio.sleep_forever()
        finally:
            cleaned_up.set()
        return Review(decision="continue")

    return review


def bash_call() -> ToolCall:
    return ToolCall(id="c1", function="bash", arguments={"cmd": "curl example.com"})


async def decide(policies: list[ReviewPolicy], call: ToolCall | None = None) -> Review:
    init_transcript(Transcript())
    call = call or bash_call()
    result = ChatMessageTool(
        content="HTTP/1.1 200 OK", tool_call_id=call.id, function=call.function
    )
    return await policy_reviewer(policies)(
        "msg", call, result, "HTTP/1.1 200 OK", ToolCallView(), []
    )


def events() -> list[ReviewEvent]:
    return [e for e in transcript().events if isinstance(e, ReviewEvent)]


async def test_every_chain_covering_the_call_runs_and_terminate_wins() -> None:
    seen: list[ToolCallView] = []

    review = await decide(
        [
            ReviewPolicy(recording_reviewer(seen), "*", chain="x"),
            ReviewPolicy(fixed_reviewer("terminate"), "*", chain="y"),
        ]
    )

    assert review.decision == "terminate"
    [summary] = [e for e in events() if e.reviewer == "policy" and e.chain is None]
    assert summary.metadata is not None
    assert summary.metadata["chains"]["y"]["decision"] == "terminate"


async def test_a_terminate_cancels_chains_still_running() -> None:
    cleaned_up = anyio.Event()

    review = await decide(
        [
            ReviewPolicy(fixed_reviewer("terminate"), "*", chain="x"),
            ReviewPolicy(waiting_reviewer(cleaned_up), "*", chain="y"),
        ]
    )

    assert review.decision == "terminate"
    assert cleaned_up.is_set()


async def test_escalation_stays_within_its_chain_and_carries_its_reason() -> None:
    seen: list[ToolCallView] = []

    review = await decide(
        [
            ReviewPolicy(fixed_reviewer("escalate"), "*", chain="x"),
            ReviewPolicy(recording_reviewer(seen), "*", chain="x"),
            ReviewPolicy(fixed_reviewer("continue"), "*", chain="y"),
        ]
    )

    assert review.decision == "continue"
    [view] = seen
    assert view.context is not None
    assert 'Escalated by fixed (chain "x")' in view.context.content


async def test_an_unanswered_escalation_continues_and_is_recorded_for_its_chain() -> (
    None
):
    review = await decide(
        [
            ReviewPolicy(fixed_reviewer("escalate"), "*", chain="x"),
            ReviewPolicy(fixed_reviewer("continue"), "*", chain="y"),
        ]
    )

    assert review.decision == "continue"
    [unheard] = [e for e in events() if e.reviewer == "policy" and e.chain == "x"]
    assert unheard.decision == "continue"


async def test_a_chain_covering_none_of_the_call_continues_like_a_lone_chain() -> None:
    seen: list[ToolCallView] = []

    review = await decide(
        [
            ReviewPolicy(recording_reviewer(seen), "bash", chain="x"),
            ReviewPolicy(fixed_reviewer("terminate"), "*", chain="y"),
        ],
        call=ToolCall(id="c2", function="python", arguments={"code": "1"}),
    )

    assert review.decision == "terminate"
    assert seen == []
    [summary] = [e for e in events() if e.reviewer == "policy" and e.chain is None]
    assert summary.metadata is not None
    assert summary.metadata["chains"]["x"]["decision"] == "continue"


async def test_an_unlabelled_list_is_one_chain_and_behaves_as_before() -> None:
    review = await decide(
        [
            ReviewPolicy(fixed_reviewer("escalate"), "*"),
            ReviewPolicy(fixed_reviewer("continue"), "*"),
        ]
    )

    assert review.decision == "continue"
    assert [(e.decision, e.chain) for e in events()] == [
        ("escalate", None),
        ("continue", None),
    ]


def test_the_chain_round_trips_through_config() -> None:
    config = config_from_review_policies(
        [ReviewPolicy(fixed_reviewer("continue"), "*", chain="x")]
    )

    assert config.reviewers[0].chain == "x"
    assert config.reviewers[0].params == {"decision": "continue"}
    [policy] = review_policies_from_config(config)
    assert policy.chain == "x"
