from typing import cast

import pytest

from inspect_ai import Task, eval, score
from inspect_ai._eval.score import resolve_scorers
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.event import ScoreEvent
from inspect_ai.log import EvalLog
from inspect_ai.log._log import EvalMetricDefinition
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    filter_scorer,
    mean,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState

_STATE = cast(TaskState, None)  # scorers below ignore state
_TARGET = Target(["x"])


@scorer(metrics=[accuracy(), stderr()])
def counting_grade(value: str = CORRECT, calls: list[str] | None = None):
    """Return a fixed grade and record each call in `calls`."""

    async def score(state: TaskState, target: Target) -> Score:
        if calls is not None:
            calls.append(target.text)
        return Score(value=value)

    return score


@scorer(metrics=[mean()])
def length_score():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=len(target.text))

    return score


def _run_eval(task: Task) -> EvalLog:
    log = eval(tasks=task, model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples is not None
    assert log.results is not None
    assert log.eval.scorers is not None
    return log


def _select_even_target(state: TaskState, target: Target) -> bool:
    return int(target.text) % 2 == 0


async def test_predicate_false_returns_none_without_calling_inner():
    calls: list[str] = []
    filtered = filter_scorer(counting_grade(calls=calls), lambda s, t: False)
    assert await filtered(_STATE, _TARGET) is None
    assert calls == []


async def test_predicate_true_delegates_to_inner():
    calls: list[str] = []
    filtered = filter_scorer(counting_grade(calls=calls), lambda s, t: True)
    result = await filtered(_STATE, _TARGET)
    assert result is not None
    assert result.value == CORRECT
    assert calls == ["x"]


async def test_async_predicate():
    calls: list[str] = []

    async def select(state: TaskState, target: Target) -> bool:
        return target.text == "x"

    filtered = filter_scorer(counting_grade(calls=calls), select)
    assert (await filtered(_STATE, _TARGET)) is not None
    assert await filtered(_STATE, Target(["y"])) is None
    assert calls == ["x"]


def test_inner_must_be_registry_scorer():
    async def plain(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT)

    with pytest.raises(PrerequisiteError):
        filter_scorer(plain, lambda s, t: True)


def test_filtered_scorer_persists_under_inner_name_and_options():
    calls: list[str] = []
    task = Task(
        dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 5)],
        scorer=filter_scorer(
            counting_grade(value=INCORRECT, calls=calls), _select_even_target
        ),
    )
    log = _run_eval(task)

    # the inner scorer only ran on the selected samples (targets 2 and 4)
    assert sorted(calls) == ["2", "4"]

    # per-sample scores are keyed on the inner scorer's name and absent for
    # filtered-out samples
    assert log.samples is not None
    for sample in log.samples:
        scores = sample.scores or {}
        if int(str(sample.target)) % 2 == 0:
            assert set(scores) == {"counting_grade"}
            assert scores["counting_grade"].value == INCORRECT
        else:
            assert scores == {}

    # score events are emitted (with the inner's args) only for scored samples
    score_events = [
        event
        for sample in log.samples
        for event in sample.events
        if isinstance(event, ScoreEvent)
    ]
    assert len(score_events) == 2
    assert all(event.scorer == "counting_grade" for event in score_events)
    assert all(
        event.scorer_args == {"value": INCORRECT, "calls": []} for event in score_events
    )

    # the log header records the inner scorer's name, options and metrics; the
    # options must be exactly the inner's so `inspect score` can re-create it
    assert log.eval.scorers is not None
    assert len(log.eval.scorers) == 1
    eval_scorer = log.eval.scorers[0]
    assert eval_scorer.name == "counting_grade"
    assert eval_scorer.options == {"value": INCORRECT, "calls": []}
    assert eval_scorer.metadata == {"filter": "_select_even_target"}
    assert isinstance(eval_scorer.metrics, list)
    metric_names = [
        m.name.removeprefix("inspect_ai/")
        for m in eval_scorer.metrics
        if isinstance(m, EvalMetricDefinition)
    ]
    assert metric_names == ["accuracy", "stderr"]


def test_metrics_computed_over_scored_samples_only():
    # even-target samples are scored CORRECT; odd ones are filtered out. If the
    # filtered-out samples were counted as zero, accuracy would be 0.5.
    task = Task(
        dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 5)],
        scorer=filter_scorer(counting_grade(value=CORRECT), _select_even_target),
    )
    log = _run_eval(task)
    assert log.results is not None
    assert len(log.results.scores) == 1
    eval_score = log.results.scores[0]
    assert eval_score.name == "counting_grade"
    assert eval_score.scorer == "counting_grade"
    assert eval_score.metrics["accuracy"].value == 1.0


def test_two_filtered_scorers_coexist_under_their_own_names():
    grade_calls: list[str] = []
    task = Task(
        dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 5)],
        scorer=[
            filter_scorer(counting_grade(calls=grade_calls), _select_even_target),
            filter_scorer(length_score(), lambda s, t: not _select_even_target(s, t)),
        ],
    )
    log = _run_eval(task)

    assert log.eval.scorers is not None
    assert [s.name for s in log.eval.scorers] == ["counting_grade", "length_score"]
    assert log.results is not None
    assert [s.name for s in log.results.scores] == ["counting_grade", "length_score"]
    assert log.results.scores[1].metrics["mean"].value == 1.0

    assert log.samples is not None
    for sample in log.samples:
        scores = sample.scores or {}
        expected = (
            "counting_grade" if int(str(sample.target)) % 2 == 0 else "length_score"
        )
        assert set(scores) == {expected}


def test_filtered_and_unfiltered_same_scorer_disambiguate_like_two_unfiltered():
    task = Task(
        dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 3)],
        scorer=[
            counting_grade(),
            filter_scorer(counting_grade(value=INCORRECT), _select_even_target),
        ],
    )
    log = _run_eval(task)
    assert log.results is not None
    assert [s.name for s in log.results.scores] == [
        "counting_grade",
        "counting_grade1",
    ]
    assert log.samples is not None
    by_target = {str(s.target): s.scores or {} for s in log.samples}
    assert set(by_target["1"]) == {"counting_grade"}
    assert set(by_target["2"]) == {"counting_grade", "counting_grade1"}
    assert by_target["2"]["counting_grade1"].value == INCORRECT


def test_task_metrics_override_keeps_filter_metadata():
    task = Task(
        dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 5)],
        scorer=filter_scorer(counting_grade(), _select_even_target),
        metrics=[mean()],
    )
    log = _run_eval(task)
    assert log.eval.scorers is not None
    eval_scorer = log.eval.scorers[0]
    assert eval_scorer.metadata == {"filter": "_select_even_target"}
    assert isinstance(eval_scorer.metrics, list)
    metric_names = [
        m.name.removeprefix("inspect_ai/")
        for m in eval_scorer.metrics
        if isinstance(m, EvalMetricDefinition)
    ]
    assert metric_names == ["mean"]
    assert log.results is not None
    assert set(log.results.scores[0].metrics) == {"mean"}


def test_rescoring_recreates_inner_scorer_without_filter():
    # the predicate is not persisted: `inspect score` re-creates the inner
    # scorer from the recorded name/options and runs it on every sample
    task = Task(
        dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 5)],
        scorer=filter_scorer(counting_grade(), _select_even_target),
    )
    log = _run_eval(task)
    assert log.samples is not None
    assert sum("counting_grade" in (s.scores or {}) for s in log.samples) == 2

    rescored = score(log, resolve_scorers(log), action="overwrite")
    assert rescored.samples is not None
    assert all("counting_grade" in (s.scores or {}) for s in rescored.samples)
    assert rescored.eval.scorers is not None
    assert rescored.eval.scorers[0].name == "counting_grade"
