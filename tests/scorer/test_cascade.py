import asyncio
import math
from typing import cast

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    PARTIAL,
    Score,
    Target,
    accuracy,
    cascade,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState

_STATE = cast(TaskState, None)  # stages below ignore state
_TARGET = Target(["x"])


def _stage(name: str, result: Score | None, calls: list[str]):
    """A stage scorer that records that it ran and returns a fixed result."""

    async def score(state: TaskState, target: Target) -> Score | None:
        calls.append(name)
        return result

    return score


def _run(scorer_fn) -> Score:
    return asyncio.run(scorer_fn(_STATE, _TARGET))


def test_first_correct_short_circuits():
    calls: list[str] = []
    fn = cascade(
        exact=_stage("exact", Score(value=CORRECT), calls),
        grader=_stage("grader", Score(value=CORRECT), calls),
    )
    result = _run(fn)
    assert calls == ["exact"]  # grader must not run
    assert result.value == CORRECT
    assert result.metadata["decided_by"] == "exact"


def test_falls_through_to_settling_stage():
    calls: list[str] = []
    fn = cascade(
        exact=_stage("exact", Score(value=INCORRECT), calls),
        grader=_stage("grader", Score(value=CORRECT), calls),
    )
    result = _run(fn)
    assert calls == ["exact", "grader"]
    assert result.value == CORRECT
    assert result.metadata["decided_by"] == "grader"


def test_no_stage_settles_returns_last_scored():
    calls: list[str] = []
    fn = cascade(
        a=_stage("a", Score(value=INCORRECT), calls),
        b=_stage("b", Score(value=INCORRECT), calls),
    )
    result = _run(fn)
    assert calls == ["a", "b"]
    assert result.value == INCORRECT
    assert result.metadata["decided_by"] == "b"


def test_declining_stage_is_skipped():
    calls: list[str] = []
    fn = cascade(
        a=_stage("a", None, calls),
        b=_stage("b", Score(value=INCORRECT), calls),
    )
    result = _run(fn)
    assert calls == ["a", "b"]
    assert result.value == INCORRECT
    assert result.metadata["decided_by"] == "b"


def test_unscored_stage_is_skipped():
    calls: list[str] = []
    fn = cascade(
        a=_stage("a", Score.unscored(), calls),
        b=_stage("b", Score(value=CORRECT), calls),
    )
    result = _run(fn)
    # the unscored (nan) stage must not be reported as the decider
    assert result.value == CORRECT
    assert result.metadata["decided_by"] == "b"


def test_all_declined_returns_unscored():
    calls: list[str] = []
    fn = cascade(
        a=_stage("a", None, calls),
        b=_stage("b", Score.unscored(), calls),
    )
    result = _run(fn)
    assert calls == ["a", "b"]
    assert math.isnan(cast(float, result.value))
    assert (result.metadata or {}).get("decided_by") is None


def test_threshold_lets_partial_settle():
    calls: list[str] = []
    fn = cascade(
        threshold=0.5,
        a=_stage("a", Score(value=PARTIAL), calls),
        b=_stage("b", Score(value=CORRECT), calls),
    )
    result = _run(fn)
    assert calls == ["a"]  # partial (0.5) settles at threshold 0.5
    assert result.value == PARTIAL
    assert result.metadata["decided_by"] == "a"


def test_default_threshold_partial_does_not_settle():
    calls: list[str] = []
    fn = cascade(
        a=_stage("a", Score(value=PARTIAL), calls),
        b=_stage("b", Score(value=CORRECT), calls),
    )
    result = _run(fn)
    assert calls == ["a", "b"]
    assert result.value == CORRECT
    assert result.metadata["decided_by"] == "b"


def test_existing_metadata_is_preserved():
    calls: list[str] = []
    fn = cascade(
        a=_stage("a", Score(value=CORRECT, metadata={"foo": "bar"}), calls),
    )
    result = _run(fn)
    assert result.metadata["foo"] == "bar"
    assert result.metadata["decided_by"] == "a"


def test_sub_scorer_score_not_mutated():
    # cascade must not write decided_by into the sub-scorer's own Score, or a
    # Score reused across samples would leak metadata between them.
    calls: list[str] = []
    original = Score(value=CORRECT)
    result = _run(cascade(a=_stage("a", original, calls)))
    assert result.metadata["decided_by"] == "a"
    assert "decided_by" not in (original.metadata or {})


@scorer(metrics=[accuracy(), stderr()])
def _fixed(value):
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=value)

    return score


def test_cascade_as_task_scorer():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2"])],
        scorer=cascade(exact=_fixed(CORRECT), grader=_fixed(INCORRECT)),
    )
    log = eval(tasks=task, model="mockllm/model")[0]
    assert log.results is not None
    assert log.results.scores is not None
    assert len(log.results.scores) == 1
    cascade_score = log.results.scores[0]
    assert cascade_score.name == "cascade"
    assert all(m in cascade_score.metrics for m in ["accuracy", "stderr"])
    assert log.samples is not None
    sample_score = log.samples[0].scores["cascade"]
    assert sample_score.value == CORRECT
    assert sample_score.metadata["decided_by"] == "exact"
