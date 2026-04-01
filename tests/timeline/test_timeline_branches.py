"""Tests for TimelineBranch discovery, forked_at resolution, and relocation."""

from datetime import datetime, timezone

from inspect_ai.event import Event, timeline_build
from inspect_ai.event._branch import BranchEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._timeline import TimelineBranch, TimelineSpan
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._model_output import ChatCompletionChoice


def _ts(seconds: float) -> datetime:
    return datetime(2025, 1, 1, 0, 0, int(seconds), tzinfo=timezone.utc)


def _model_event(
    *,
    uuid: str,
    span_id: str,
    ts: float,
    output_message_id: str,
    input_messages: list | None = None,
) -> ModelEvent:
    """Create a minimal ModelEvent with output message id."""
    return ModelEvent(
        uuid=uuid,
        span_id=span_id,
        timestamp=_ts(ts),
        working_start=ts,
        model="test-model",
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        input=input_messages or [ChatMessageUser(content="hello", id="user-1")],
        output=ModelOutput(
            model="test-model",
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content="response", id=output_message_id
                    ),
                    stop_reason="stop",
                )
            ],
            usage=ModelUsage(input_tokens=10, output_tokens=10, total_tokens=20),
        ),
    )


def _span_begin(
    *,
    uuid: str,
    id: str,
    parent_id: str | None = None,
    ts: float,
    name: str,
    span_type: str | None = None,
) -> SpanBeginEvent:
    return SpanBeginEvent(
        uuid=uuid,
        span_id=parent_id,
        timestamp=_ts(ts),
        working_start=ts,
        id=id,
        parent_id=parent_id,
        name=name,
        type=span_type,
    )


def _span_end(
    *, uuid: str, id: str, parent_id: str | None = None, ts: float
) -> SpanEndEvent:
    return SpanEndEvent(
        uuid=uuid,
        span_id=parent_id,
        timestamp=_ts(ts),
        working_start=ts,
        id=id,
    )


def _branch_event(
    *, uuid: str, span_id: str, ts: float, from_span: str, from_message: str
) -> BranchEvent:
    return BranchEvent(
        uuid=uuid,
        span_id=span_id,
        timestamp=_ts(ts),
        working_start=ts,
        from_span=from_span,
        from_message=from_message,
    )


def test_branch_with_branch_event_creates_timeline_branch() -> None:
    """A type='branch' span containing a BranchEvent becomes a TimelineBranch."""
    events: list[Event] = [
        # Agent span
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-1"),
        _model_event(uuid="m2", span_id="agent", ts=2, output_message_id="msg-2"),
        # Branch span (child of agent)
        _span_begin(
            uuid="sb2",
            id="branch-1",
            parent_id="agent",
            ts=3,
            name="branch",
            span_type="branch",
        ),
        _branch_event(
            uuid="be1",
            span_id="branch-1",
            ts=3.1,
            from_span="agent",
            from_message="msg-1",
        ),
        _model_event(uuid="m3", span_id="branch-1", ts=4, output_message_id="msg-3"),
        _span_end(uuid="se2", id="branch-1", parent_id="agent", ts=5),
        _span_end(uuid="se1", id="agent", ts=6),
    ]

    timeline = timeline_build(events)
    root = timeline.root

    # Find the agent span (may be root or nested)
    agent = _find_span(root, "agent")
    assert agent is not None, "Agent span not found"
    assert len(agent.branches) == 1
    branch = agent.branches[0]
    assert isinstance(branch, TimelineBranch)
    assert branch.forked_at == "m1"  # resolved from msg-1 → model event m1


def test_branch_without_branch_event_becomes_content() -> None:
    """A type='branch' span without a BranchEvent is processed as normal content."""
    events: list[Event] = [
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-1"),
        # Branch span without BranchEvent
        _span_begin(
            uuid="sb2",
            id="branch-1",
            parent_id="agent",
            ts=2,
            name="branch",
            span_type="branch",
        ),
        _model_event(uuid="m2", span_id="branch-1", ts=3, output_message_id="msg-2"),
        _span_end(uuid="se2", id="branch-1", parent_id="agent", ts=4),
        _span_end(uuid="se1", id="agent", ts=5),
    ]

    timeline = timeline_build(events)
    root = timeline.root

    # Find the agent span
    agent = _find_span(root, "agent")
    assert agent is not None, "Agent span not found"
    # No branches — content absorbed into parent
    assert len(agent.branches) == 0
    # Both model events should be in content
    model_events = [
        item
        for item in agent.content
        if hasattr(item, "event") and item.event.event == "model"
    ]
    assert len(model_events) == 2


def test_nested_branch_relocated_to_parent_branch() -> None:
    """Branch 2 forking from branch 1 is nested inside branch 1."""
    events: list[Event] = [
        # Agent span
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-1"),
        # Branch 1 — forks from agent
        _span_begin(
            uuid="sb2",
            id="branch-1",
            parent_id="agent",
            ts=2,
            name="branch",
            span_type="branch",
        ),
        _branch_event(
            uuid="be1",
            span_id="branch-1",
            ts=2.1,
            from_span="agent",
            from_message="msg-1",
        ),
        _model_event(uuid="m2", span_id="branch-1", ts=3, output_message_id="msg-2"),
        _span_end(uuid="se2", id="branch-1", parent_id="agent", ts=4),
        # Branch 2 — forks from branch-1
        _span_begin(
            uuid="sb3",
            id="branch-2",
            parent_id="agent",
            ts=5,
            name="branch",
            span_type="branch",
        ),
        _branch_event(
            uuid="be2",
            span_id="branch-2",
            ts=5.1,
            from_span="branch-1",
            from_message="msg-2",
        ),
        _model_event(uuid="m3", span_id="branch-2", ts=6, output_message_id="msg-3"),
        _span_end(uuid="se3", id="branch-2", parent_id="agent", ts=7),
        _span_end(uuid="se1", id="agent", ts=8),
    ]

    timeline = timeline_build(events)
    root = timeline.root

    # Find the agent span
    agent = _find_span(root, "agent")
    assert agent is not None, "Agent span not found"

    # Agent should have 1 branch (branch 1); branch 2 was relocated
    assert len(agent.branches) == 1
    branch1 = agent.branches[0]
    assert branch1.forked_at == "m1"

    # Branch 1's content span should have 1 nested branch (branch 2)
    assert isinstance(branch1.content, TimelineSpan)
    assert len(branch1.content.branches) == 1
    branch2 = branch1.content.branches[0]
    assert branch2.forked_at == "m2"


def test_forked_at_resolves_via_message_lookup() -> None:
    """forked_at correctly maps message_id to event UUID."""
    events: list[Event] = [
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-A"),
        _model_event(uuid="m2", span_id="agent", ts=2, output_message_id="msg-B"),
        _model_event(uuid="m3", span_id="agent", ts=3, output_message_id="msg-C"),
        # Branch forking from the second model event
        _span_begin(
            uuid="sb2",
            id="branch-1",
            parent_id="agent",
            ts=4,
            name="branch",
            span_type="branch",
        ),
        _branch_event(
            uuid="be1",
            span_id="branch-1",
            ts=4.1,
            from_span="agent",
            from_message="msg-B",
        ),
        _model_event(uuid="m4", span_id="branch-1", ts=5, output_message_id="msg-D"),
        _span_end(uuid="se2", id="branch-1", parent_id="agent", ts=6),
        _span_end(uuid="se1", id="agent", ts=7),
    ]

    timeline = timeline_build(events)
    root = timeline.root

    agent = _find_span(root, "agent")
    assert agent is not None, "Agent span not found"
    assert len(agent.branches) == 1
    # forked_at should be "m2" (the event that produced msg-B)
    assert agent.branches[0].forked_at == "m2"


def _find_span(span: TimelineSpan, span_id: str) -> TimelineSpan | None:
    """Recursively find a TimelineSpan by id."""
    if span.id == span_id:
        return span
    for item in span.content:
        if isinstance(item, TimelineSpan):
            result = _find_span(item, span_id)
            if result:
                return result
    return None
