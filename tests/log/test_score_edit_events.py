"""Tests for ScoreEditEvent span integration."""

import pytest

from inspect_ai import Task, eval_async, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.event._score_edit import ScoreEditEvent
from inspect_ai.event._span import SpanEndEvent
from inspect_ai.event._tree import event_tree, walk_node_spans
from inspect_ai.log._score import edit_score
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.scorer._metric import ScoreEdit
from inspect_ai.scorer._scorer import Scorer
from inspect_ai.solver import TaskState


@scorer(metrics=[mean()])
def test_scorer() -> Scorer:
    async def score(state: TaskState, target: Target):
        return Score(value=1)

    return score


@task
def test_task():
    return Task(
        dataset=MemoryDataset([Sample(input="test") for _ in range(3)]),
        plan=[],
        scorer=test_scorer(),
    )


@pytest.mark.anyio
async def test_score_edit_event_span_integration():
    """Test that ScoreEditEvent is properly integrated into the scorers span."""
    logs = await eval_async(test_task())
    log = logs[0]

    sample = log.samples[0]

    edit = ScoreEdit(value=4, explanation="Span integration test")
    edit_score(log, sample.id, "test_scorer", edit)

    # Build the event tree to analyze span structure
    tree = event_tree(sample.events)

    # Find the scorers span
    existing_scorers_span = next(
        (
            node
            for node in walk_node_spans(tree)
            if node.type == "scorers" and node.name == "scorers"
        ),
        None,
    )

    assert existing_scorers_span is not None, "Should have a scorers span"

    # Find the ScoreEditEvent
    score_edit_event = next(
        (event for event in sample.events if isinstance(event, ScoreEditEvent)), None
    )

    assert score_edit_event is not None, "Should have a ScoreEditEvent"

    assert score_edit_event.span_id == existing_scorers_span.id, (
        "ScoreEditEvent should be associated with scorers span"
    )

    assert any(
        isinstance(child, ScoreEditEvent) for child in existing_scorers_span.children
    ), "ScoreEditEvent should be structurally positioned as a child of the scorers span"

    score_edit_idx = None
    span_end_idx = None

    for i, event in enumerate(sample.events):
        if isinstance(event, ScoreEditEvent):
            score_edit_idx = i
        elif isinstance(event, SpanEndEvent) and event.id == existing_scorers_span.id:
            span_end_idx = i

    assert score_edit_idx is not None, "ScoreEditEvent not found in events list"
    assert span_end_idx is not None, "Scorers span end not found in events list"
    assert score_edit_idx < span_end_idx, (
        f"ScoreEditEvent (index {score_edit_idx}) should appear before scorers span end (index {span_end_idx})"
    )
