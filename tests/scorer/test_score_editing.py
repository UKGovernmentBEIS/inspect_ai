"""Tests for score editing functionality."""

from datetime import datetime

import pytest

from inspect_ai import Task, eval_async, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log._edit import edit_score, recompute_metrics
from inspect_ai.scorer import Score, Target, accuracy, mean, scorer
from inspect_ai.scorer._metric import ProvenanceData, ScoreEdit
from inspect_ai.solver import TaskState


@scorer(metrics=[mean()])
def single_metric_scorer():
    async def score(state: TaskState, target: Target):
        return Score(value=1)

    return score


@scorer(metrics=[accuracy()])
def accuracy_scorer():
    async def score(state: TaskState, target: Target):
        return Score(value="C")

    return score


@scorer(metrics=[mean(), accuracy()])
def multi_metric_scorer():
    async def score(state: TaskState, target: Target):
        return Score(value="C")

    return score


@task
def single_metric_task():
    return Task(
        dataset=MemoryDataset([Sample(input="") for _ in range(10)]),
        plan=[],
        scorer=single_metric_scorer(),
    )


@task
def accuracy_task():
    return Task(
        dataset=MemoryDataset([Sample(input="") for _ in range(10)]),
        plan=[],
        scorer=accuracy_scorer(),
    )


@task
def multi_metric_task():
    return Task(
        dataset=MemoryDataset([Sample(input="") for _ in range(8)]),
        plan=[],
        scorer=multi_metric_scorer(),
    )


# Core Score/ScoreEdit Tests
def test_score_creation_legacy_format():
    """Test that legacy Score(value=1.0) format still works."""
    score = Score(value=1.0)
    assert score.value == 1.0
    assert len(score.history) == 1
    assert score.history[0].value == 1.0
    assert score.history[0].provenance is None
    assert not score.was_edited


def test_score_creation_with_explanation():
    """Test Score creation with explanation field."""
    score = Score(value="C", explanation="This is correct")
    assert score.value == "C"
    assert score.explanation == "This is correct"
    assert score.history[0].explanation == "This is correct"


def test_score_creation_with_none_explanation():
    """Test Score creation with explicit None explanation."""
    score = Score(value="C", explanation=None)
    assert score.value == "C"
    assert score.explanation is None
    assert score.history[0].explanation is None


def test_score_edit_creation():
    """Test ScoreEdit creation with and without provenance."""
    # Original score edit (no provenance)
    original = ScoreEdit(value="C", answer="Yes", explanation=None, provenance=None)
    assert original.value == "C"
    assert original.answer == "Yes"
    assert original.explanation is None
    assert original.provenance is None

    # Edit with provenance
    provenance = ProvenanceData(author="test_user", reason="Manual correction")
    edit = ScoreEdit(value="I", provenance=provenance)
    assert edit.value == "I"
    assert edit.answer == "UNCHANGED"
    assert edit.explanation == "UNCHANGED"
    assert edit.provenance.author == "test_user"


def test_score_properties():
    """Test Score property access after edits."""
    score = Score(value="C", answer="Yes", explanation="Original")

    # Add an edit
    provenance = ProvenanceData(author="editor", reason="Correction")
    edit = ScoreEdit(
        value="I", explanation="Updated explanation", provenance=provenance
    )
    score.history.append(edit)

    # Properties should return most recent values
    assert score.value == "I"
    assert score.answer == "Yes"  # Unchanged from original
    assert score.explanation == "Updated explanation"
    assert score.original_value == "C"
    assert score.was_edited


def test_score_history_tracking():
    """Test that score history accumulates correctly."""
    score = Score(value=1.0)

    # Add multiple edits
    edit1 = ScoreEdit(value=2.0)
    edit2 = ScoreEdit(value=3.0, explanation="Final value")

    score.history.append(edit1)
    score.history.append(edit2)

    assert len(score.history) == 3  # Original + 2 edits
    assert score.value == 3.0
    assert score.explanation == "Final value"
    assert score.original_value == 1.0
    assert score.was_edited


# Backward Compatibility Tests
def test_score_model_validate_old_format():
    """Test deserializing old Score format."""
    old_data = {"value": "C", "answer": "Yes"}
    score = Score.model_validate(old_data)

    assert score.value == "C"
    assert score.answer == "Yes"
    assert score.explanation is None
    assert len(score.history) == 1
    assert score.history[0].provenance is None


def test_score_model_validate_old_format_with_null():
    """Test deserializing old Score format with null explanation."""
    old_data = {"value": "C", "answer": "Yes", "explanation": None}
    score = Score.model_validate(old_data)

    assert score.value == "C"
    assert score.answer == "Yes"
    assert score.explanation is None
    assert score.history[0].explanation is None


def test_score_model_dump_legacy():
    """Test serializing legacy scores (no edits)."""
    score = Score(value="C", answer="Yes")
    serialized = score.model_dump()

    # Should use legacy format
    assert serialized == {"value": "C", "answer": "Yes"}
    assert "history" not in serialized


def test_score_model_dump_with_edits():
    """Test serializing scores with edits."""
    score = Score(value="C", answer="Yes")
    edit = ScoreEdit(value="I")  # Only changes value, answer stays "UNCHANGED"
    score.history.append(edit)

    serialized = score.model_dump()

    # Should include both history and computed fields
    assert "history" in serialized
    assert serialized["value"] == "I"
    assert serialized["answer"] == "Yes"  # Should preserve original answer


# Provenance Tests
def test_provenance_data_creation():
    """Test ProvenanceData creation with timestamp."""
    before = datetime.now()
    provenance = ProvenanceData(author="test_user", reason="Manual edit")
    after = datetime.now()

    assert provenance.author == "test_user"
    assert provenance.reason == "Manual edit"
    assert before <= provenance.timestamp <= after
    assert isinstance(provenance.metadata, dict)


# Metric Recomputation Tests
@pytest.mark.anyio
async def test_recompute_single_metric():
    """Test recomputing single metric after score edits."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    assert log.results.scores[0].metrics["mean"].value == 1

    # Edit every other sample to 0
    for i, sample in enumerate(log.samples):
        if i % 2 == 0:
            continue
        edit = ScoreEdit(value=0)
        edit_score(
            log, sample.id, "single_metric_scorer", edit, should_recompute_metrics=False
        )

    recompute_metrics(log)
    assert log.results.scores[0].metrics["mean"].value == 0.5


@pytest.mark.anyio
async def test_recompute_accuracy_metric():
    """Test recomputing accuracy metric after score edits."""
    logs = await eval_async(accuracy_task())
    log = logs[0]

    assert log.results.scores[0].metrics["accuracy"].value == 1.0

    # Edit half to incorrect
    for i, sample in enumerate(log.samples):
        if i < 5:
            edit = ScoreEdit(value="I")
            edit_score(
                log, sample.id, "accuracy_scorer", edit, should_recompute_metrics=False
            )

    recompute_metrics(log)
    assert log.results.scores[0].metrics["accuracy"].value == 0.5


@pytest.mark.anyio
async def test_recompute_multiple_metrics():
    """Test recomputing multiple metrics on same scorer."""
    logs = await eval_async(multi_metric_task())
    log = logs[0]

    # Initial values
    assert log.results.scores[0].metrics["mean"].value == 1.0
    assert log.results.scores[0].metrics["accuracy"].value == 1.0

    # Edit half to incorrect/zero
    for i, sample in enumerate(log.samples):
        if i < 4:
            edit = ScoreEdit(
                value="I"
            )  # This becomes 0 for mean, incorrect for accuracy
            edit_score(
                log,
                sample.id,
                "multi_metric_scorer",
                edit,
                should_recompute_metrics=False,
            )

    recompute_metrics(log)
    assert log.results.scores[0].metrics["mean"].value == 0.5
    assert log.results.scores[0].metrics["accuracy"].value == 0.5


@pytest.mark.anyio
async def test_edit_score_with_provenance():
    """Test editing scores with provenance tracking."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    sample = log.samples[0]
    original_value = sample.scores["single_metric_scorer"].value

    # Edit with provenance
    provenance = ProvenanceData(author="test_editor", reason="Quality improvement")
    edit = ScoreEdit(value=5, provenance=provenance)
    edit_score(log, sample.id, "single_metric_scorer", edit)

    # Check the score was edited
    updated_score = sample.scores["single_metric_scorer"]
    assert updated_score.value == 5
    assert updated_score.original_value == original_value
    assert updated_score.was_edited
    assert len(updated_score.history) == 2
    assert updated_score.history[1].provenance.author == "test_editor"


@pytest.mark.anyio
async def test_edit_score_error_cases():
    """Test error handling in edit_score function."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    edit = ScoreEdit(value=5)

    # Test invalid sample ID
    with pytest.raises(ValueError, match="Sample with id invalid_id not found"):
        edit_score(log, "invalid_id", "single_metric_scorer", edit)

    # Test invalid score name
    with pytest.raises(ValueError, match="Score 'invalid_scorer' not found"):
        edit_score(log, log.samples[0].id, "invalid_scorer", edit)


@pytest.mark.anyio
async def test_no_auto_recompute():
    """Test that edits don't auto-recompute when disabled."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    original_mean = log.results.scores[0].metrics["mean"].value

    # Edit a score without recomputing
    edit = ScoreEdit(value=100)
    edit_score(
        log,
        log.samples[0].id,
        "single_metric_scorer",
        edit,
        should_recompute_metrics=False,
    )

    # Metric should be unchanged
    assert log.results.scores[0].metrics["mean"].value == original_mean

    # Manual recompute should update it
    recompute_metrics(log)
    assert log.results.scores[0].metrics["mean"].value != original_mean
