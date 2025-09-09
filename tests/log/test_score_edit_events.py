"""Tests for score edit events in logs."""

import pytest

from inspect_ai import Task, eval_async, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log._edit import edit_score
from inspect_ai.log._transcript import ScoreEditEvent
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.scorer._metric import ProvenanceData, ScoreEdit
from inspect_ai.solver import TaskState


@scorer(metrics=[mean()])
def test_scorer():
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


def test_score_edit_event_creation():
    """Test ScoreEditEvent structure and creation."""
    provenance = ProvenanceData(author="test_user", reason="Manual correction")
    edit = ScoreEdit(value="I", explanation="Updated", provenance=provenance)

    event = ScoreEditEvent(score_name="test_scorer", edit=edit)

    assert event.event == "score_edit"
    assert event.score_name == "test_scorer"
    assert event.edit.value == "I"
    assert event.edit.explanation == "Updated"
    assert event.edit.provenance.author == "test_user"


@pytest.mark.anyio
async def test_score_edit_event_in_log():
    """Test that score edit events are properly logged in sample events."""
    logs = await eval_async(test_task())
    log = logs[0]

    sample = log.samples[0]
    original_event_count = len(sample.events)

    # Edit a score
    provenance = ProvenanceData(author="test_editor", reason="Correction")
    edit = ScoreEdit(value=5, provenance=provenance)
    edit_score(log, sample.id, "test_scorer", edit)

    # Check that an event was added
    assert len(sample.events) == original_event_count + 1

    # Check the event details
    score_edit_event = sample.events[-1]
    assert isinstance(score_edit_event, ScoreEditEvent)
    assert score_edit_event.event == "score_edit"
    assert score_edit_event.score_name == "test_scorer"
    assert score_edit_event.edit.value == 5
    assert score_edit_event.edit.provenance.author == "test_editor"


@pytest.mark.anyio
async def test_multiple_score_edits_create_multiple_events():
    """Test that multiple edits create multiple events."""
    logs = await eval_async(test_task())
    log = logs[0]

    sample = log.samples[0]
    original_event_count = len(sample.events)

    # Make multiple edits
    edit1 = ScoreEdit(value=2)
    edit2 = ScoreEdit(value=3, explanation="Final value")

    edit_score(log, sample.id, "test_scorer", edit1)
    edit_score(log, sample.id, "test_scorer", edit2)

    # Should have 2 new events
    assert len(sample.events) == original_event_count + 2

    # Check both events
    event1 = sample.events[-2]
    event2 = sample.events[-1]

    assert isinstance(event1, ScoreEditEvent)
    assert isinstance(event2, ScoreEditEvent)
    assert event1.edit.value == 2
    assert event2.edit.value == 3
    assert event2.edit.explanation == "Final value"
