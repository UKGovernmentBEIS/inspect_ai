"""Tests for score editing functionality."""

import pytest

from inspect_ai import Task, eval_async, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log._edit import ProvenanceData
from inspect_ai.log._metric import recompute_metrics
from inspect_ai.log._score import edit_score
from inspect_ai.scorer import Score, Target, accuracy, mean, scorer
from inspect_ai.scorer._metric import ScoreEdit
from inspect_ai.scorer._scorer import Scorer
from inspect_ai.solver import TaskState


@scorer(metrics=[mean()])
def single_metric_scorer() -> Scorer:
    async def score(state: TaskState, target: Target):
        return Score(value=1)

    return score


@scorer(metrics=[accuracy()])
def accuracy_scorer() -> Scorer:
    async def score(state: TaskState, target: Target):
        return Score(value="C")

    return score


@scorer(metrics=[mean(), accuracy()])
def multi_metric_scorer() -> Scorer:
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


def test_direct_score_mutation_no_history():
    """Test that directly mutating score doesn't affect history."""
    score = Score(value="C", explanation="Original")

    score.value = "I"
    score.explanation = "Updated"

    assert len(score.history) == 0
    assert score.value == "I"
    assert score.explanation == "Updated"


@scorer(metrics={"one": [mean()], "two": [mean()], "three": [mean()]})
def dict_metric_scorer() -> Scorer:
    async def score(state: TaskState, target: Target):
        return Score(value={"one": 1, "two": 2, "three": 3})

    return score


@task
def dict_metric_task():
    return Task(
        dataset=MemoryDataset([Sample(input="") for _ in range(6)]),
        plan=[],
        scorer=dict_metric_scorer(),
    )


@scorer(metrics=[mean()])
def first_scorer() -> Scorer:
    async def score(state: TaskState, target: Target):
        return Score(value=0.8)

    return score


@scorer(metrics=[mean(), accuracy()])
def second_scorer() -> Scorer:
    async def score(state: TaskState, target: Target):
        return Score(value="C")

    return score


@task
def multi_scorer_task():
    return Task(
        dataset=MemoryDataset([Sample(input="") for _ in range(4)]),
        plan=[],
        scorer=[first_scorer(), second_scorer()],
    )


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
            log, sample.id, "single_metric_scorer", edit, recompute_metrics=False
        )

    recompute_metrics(log)
    assert log.results.scores[0].metrics["mean"].value == 0.5


@pytest.mark.anyio
async def test_recompute_dict_metrics():
    """Test recomputing dict-based metrics after score edits."""
    logs = await eval_async(dict_metric_task(), model="mockllm/model")
    log = logs[0]

    one_score = next(s for s in log.results.scores if s.name == "one")
    two_score = next(s for s in log.results.scores if s.name == "two")
    three_score = next(s for s in log.results.scores if s.name == "three")

    assert one_score.metrics["mean"].value == 1.0
    assert two_score.metrics["mean"].value == 2.0
    assert three_score.metrics["mean"].value == 3.0

    # Edit half of samples to change their dict values
    for i, sample in enumerate(log.samples):
        if i < 3:
            edit = ScoreEdit(value={"one": 10, "two": 20, "three": 30})
            edit_score(
                log,
                sample.id,
                "dict_metric_scorer",
                edit,
                recompute_metrics=False,
            )

    recompute_metrics(log)
    # Should be averages of original and new values
    one_score_after = next(s for s in log.results.scores if s.name == "one")
    two_score_after = next(s for s in log.results.scores if s.name == "two")
    three_score_after = next(s for s in log.results.scores if s.name == "three")

    assert one_score_after.metrics["mean"].value == 5.5  # (1*3 + 10*3) / 6
    assert two_score_after.metrics["mean"].value == 11.0  # (2*3 + 20*3) / 6
    assert three_score_after.metrics["mean"].value == 16.5  # (3*3 + 30*3) / 6


@pytest.mark.anyio
async def test_recompute_multiple_scorers_metrics():
    """Test recomputing metrics when multiple scorers are present."""
    logs = await eval_async(multi_scorer_task())
    log = logs[0]

    first_score_result = next(s for s in log.results.scores if s.name == "first_scorer")
    second_score_result = next(
        s for s in log.results.scores if s.name == "second_scorer"
    )

    assert first_score_result.metrics["mean"].value == 0.8
    assert second_score_result.metrics["mean"].value == 1.0
    assert second_score_result.metrics["accuracy"].value == 1.0

    # Edit first scorer values in half the samples
    for i, sample in enumerate(log.samples):
        if i < 2:
            edit = ScoreEdit(value=0.2)
            edit_score(
                log,
                sample.id,
                "first_scorer",
                edit,
                recompute_metrics=False,
            )

    # Edit second scorer values in different samples
    for i, sample in enumerate(log.samples):
        if i >= 2:
            edit = ScoreEdit(value="I")
            edit_score(
                log,
                sample.id,
                "second_scorer",
                edit,
                recompute_metrics=False,
            )

    recompute_metrics(log)

    # Check updated metrics
    first_score_result = next(s for s in log.results.scores if s.name == "first_scorer")
    second_score_result = next(
        s for s in log.results.scores if s.name == "second_scorer"
    )

    assert first_score_result.metrics["mean"].value == 0.5  # (0.2*2 + 0.8*2) / 4
    assert (
        second_score_result.metrics["mean"].value == 0.5
    )  # (1.0*2 + 0.0*2) / 4 = 0.5 since "C"->1.0, "I"->0.0
    assert (
        second_score_result.metrics["accuracy"].value == 0.5
    )  # 2 correct, 2 incorrect


@pytest.mark.anyio
async def test_recompute_custom_reducers():
    """Test recomputing metrics with custom reducers."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    assert log.results.scores[0].metrics["mean"].value == 1.0

    # Edit some samples to different values
    edit_values = [0.5, 2.0, 1.5]
    for i, value in enumerate(edit_values):
        edit = ScoreEdit(value=value)
        edit_score(
            log,
            log.samples[i].id,
            "single_metric_scorer",
            edit,
            recompute_metrics=False,
        )

    # Set up custom reducer
    log.eval.config.epochs_reducer = ["max"]
    recompute_metrics(log)

    # With max_score reducer applied to single epoch, it returns the computed metric
    # Mean = (0.5 + 2.0 + 1.5 + 7*1.0) / 10 = 11.0 / 10 = 1.1
    # Max reducer on single epoch: max([1.1]) = 1.1
    assert log.results.scores[0].metrics["mean"].value == 1.1


@pytest.mark.anyio
async def test_recompute_multiple_metrics():
    """Test recomputing multiple metrics on same scorer."""
    logs = await eval_async(multi_metric_task(), model="mockllm/model")
    log = logs[0]

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
                recompute_metrics=False,
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

    provenance = ProvenanceData(author="test_editor", reason="Quality improvement")
    edit = ScoreEdit(value=5, provenance=provenance)
    edit_score(log, sample.id, "single_metric_scorer", edit)

    # Check the score was edited
    updated_score = sample.scores["single_metric_scorer"]
    assert updated_score.value == 5
    assert updated_score.history[0].value == original_value
    assert len(updated_score.history) == 2
    assert updated_score.history[1].provenance.author == "test_editor"


@pytest.mark.anyio
async def test_edit_score_error_cases():
    """Test error handling in edit_score function."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    edit = ScoreEdit(value=5)

    with pytest.raises(ValueError, match="Sample with id invalid_id not found"):
        edit_score(log, "invalid_id", "single_metric_scorer", edit)

    with pytest.raises(ValueError, match="Score 'invalid_scorer' not found"):
        edit_score(log, log.samples[0].id, "invalid_scorer", edit)


@pytest.mark.anyio
async def test_edit_score_without_recompute():
    """Test that edits don't auto-recompute when disabled."""
    logs = await eval_async(single_metric_task())
    log = logs[0]

    original_mean = log.results.scores[0].metrics["mean"].value

    edit = ScoreEdit(value=100)
    edit_score(
        log,
        log.samples[0].id,
        "single_metric_scorer",
        edit,
        recompute_metrics=False,
    )

    assert log.results.scores[0].metrics["mean"].value == original_mean

    recompute_metrics(log)
    assert log.results.scores[0].metrics["mean"].value != original_mean


@pytest.mark.anyio
async def test_edit_score_multiple_epochs_with_epoch_specified():
    """Test editing scores when there are multiple epochs and epoch is specified."""
    logs = await eval_async(single_metric_task(), epochs=3)
    log = logs[0]

    sample_id = log.samples[0].id

    edit = ScoreEdit(value=5)
    edit_score(
        log, sample_id, "single_metric_scorer", edit, recompute_metrics=False, epoch=1
    )

    for sample in log.samples:
        if sample.id == sample_id:
            expected = 5 if sample.epoch == 1 else 1
            assert sample.scores["single_metric_scorer"].value == expected


@pytest.mark.anyio
async def test_edit_score_multiple_epochs_without_epoch_fails():
    """Test that editing without specifying epoch fails when there are multiple epochs."""
    logs = await eval_async(single_metric_task(), epochs=2)
    log = logs[0]

    sample_id = log.samples[0].id

    edit = ScoreEdit(value=5)

    with pytest.raises(
        ValueError,
        match=r"Multiple samples found with id .+\. You must specify the epoch parameter\.",
    ):
        edit_score(log, sample_id, "single_metric_scorer", edit)


@pytest.mark.anyio
async def test_edit_score_invalid_epoch():
    """Test that editing with an invalid epoch raises an error."""
    logs = await eval_async(single_metric_task(), epochs=2)
    log = logs[0]

    sample_id = log.samples[0].id

    edit = ScoreEdit(value=5)

    with pytest.raises(ValueError, match=r"Sample with id .+ and epoch 5 not found"):
        edit_score(log, sample_id, "single_metric_scorer", edit, epoch=5)
