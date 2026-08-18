"""Tests for branch discovery, branched_from, and relocation."""

from datetime import datetime, timezone

from inspect_ai.event import Event, timeline_build
from inspect_ai.event._branch import BranchEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._timeline import TimelineSpan
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
    *, uuid: str, span_id: str, ts: float, from_anchor: str
) -> BranchEvent:
    return BranchEvent(
        uuid=uuid,
        span_id=span_id,
        timestamp=_ts(ts),
        working_start=ts,
        from_anchor=from_anchor,
    )


def _find_span(span: TimelineSpan, span_id: str) -> TimelineSpan | None:
    """Recursively find a TimelineSpan by id."""
    if span.id == span_id:
        return span
    for item in span.content:
        if isinstance(item, TimelineSpan):
            result = _find_span(item, span_id)
            if result:
                return result
    for branch in span.branches:
        result = _find_span(branch, span_id)
        if result:
            return result
    return None


def test_branch_with_branch_event_creates_branch_span() -> None:
    """A type='branch' span containing a BranchEvent becomes a branch in branches."""
    events: list[Event] = [
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-1"),
        _model_event(uuid="m2", span_id="agent", ts=2, output_message_id="msg-2"),
        _span_begin(
            uuid="sb2",
            id="branch-1",
            parent_id="agent",
            ts=3,
            name="branch",
            span_type="branch",
        ),
        _branch_event(uuid="be1", span_id="branch-1", ts=3.1, from_anchor="msg-1"),
        _model_event(uuid="m3", span_id="branch-1", ts=4, output_message_id="msg-3"),
        _span_end(uuid="se2", id="branch-1", parent_id="agent", ts=5),
        _span_end(uuid="se1", id="agent", ts=6),
    ]

    timeline = timeline_build(events)
    agent = _find_span(timeline.root, "agent")
    assert agent is not None

    assert len(agent.branches) == 1
    branch = agent.branches[0]
    assert branch.span_type == "branch"
    assert branch.branched_from == "msg-1"


def test_branch_without_branch_event_becomes_content() -> None:
    """A type='branch' span without a BranchEvent is processed as normal content."""
    events: list[Event] = [
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-1"),
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
    agent = _find_span(timeline.root, "agent")
    assert agent is not None

    assert len(agent.branches) == 0
    model_events = [
        item
        for item in agent.content
        if hasattr(item, "event") and item.event.event == "model"
    ]
    assert len(model_events) == 2


def test_branched_from_stores_message_id() -> None:
    """branched_from stores the message_id directly from BranchEvent."""
    events: list[Event] = [
        _span_begin(uuid="sb1", id="agent", ts=0, name="main", span_type="agent"),
        _model_event(uuid="m1", span_id="agent", ts=1, output_message_id="msg-A"),
        _model_event(uuid="m2", span_id="agent", ts=2, output_message_id="msg-B"),
        _model_event(uuid="m3", span_id="agent", ts=3, output_message_id="msg-C"),
        _span_begin(
            uuid="sb2",
            id="branch-1",
            parent_id="agent",
            ts=4,
            name="branch",
            span_type="branch",
        ),
        _branch_event(uuid="be1", span_id="branch-1", ts=4.1, from_anchor="msg-B"),
        _model_event(uuid="m4", span_id="branch-1", ts=5, output_message_id="msg-D"),
        _span_end(uuid="se2", id="branch-1", parent_id="agent", ts=6),
        _span_end(uuid="se1", id="agent", ts=7),
    ]

    timeline = timeline_build(events)
    agent = _find_span(timeline.root, "agent")
    assert agent is not None

    assert len(agent.branches) == 1
    assert agent.branches[0].branched_from == "msg-B"
