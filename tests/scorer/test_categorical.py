import os
import tempfile
from typing import cast

import pytest

from inspect_ai import Epochs, Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log, recompute_metrics, write_eval_log
from inspect_ai.scorer import (
    Metric,
    Score,
    Scorer,
    Target,
    Value,
    accuracy,
    categorical,
    frequency,
    scorer,
)
from inspect_ai.scorer._metric import (
    MetricProtocol,
    SampleScore,
    metric,
    metric_create,
    metric_scores,
)
from inspect_ai.solver import TaskState
from inspect_ai.util import StrEnum


class Verdict(StrEnum):
    YES = "yes"
    NO = "no"
    UNSURE = "unsure"


class Sabotage(StrEnum):
    NONE = "none"
    SUBTLE = "subtle"
    OVERT = "overt"


def ss(v: Value) -> SampleScore:
    return SampleScore(score=Score(value=v))


def call(metric: Metric, scores: list[SampleScore]) -> dict[str, float]:
    return cast(dict[str, float], cast(MetricProtocol, metric)(scores))


# ---------------------------------------------------------------------------
# frequency() unit tests
# ---------------------------------------------------------------------------


def test_frequency_explicit_categories() -> None:
    result = call(frequency(categories=Verdict), [ss("yes"), ss("yes"), ss("no")])
    assert result == {
        "yes": pytest.approx(2 / 3),
        "no": pytest.approx(1 / 3),
        "unsure": 0.0,
    }


def test_frequency_no_categories_reports_observed_only() -> None:
    result = call(frequency(), [ss("yes"), ss("yes"), ss("no")])
    assert result == {"yes": pytest.approx(2 / 3), "no": pytest.approx(1 / 3)}


def test_frequency_declared_plus_unexpected_value() -> None:
    # values outside the declared domain are appended after declared categories
    result = call(frequency(categories=Verdict), [ss("yes"), ss("no"), ss("weird")])
    assert list(result) == ["yes", "no", "unsure", "weird"]
    assert result["unsure"] == 0.0
    assert result["weird"] == pytest.approx(1 / 3)


def test_frequency_normalize_false() -> None:
    result = call(
        frequency(categories=Verdict, normalize=False),
        [ss("yes")] * 3 + [ss("no")],
    )
    assert result == {"yes": 3.0, "no": 1.0, "unsure": 0.0}


def test_frequency_rejects_dict_scores() -> None:
    with pytest.raises(TypeError, match="dict-valued"):
        call(frequency(), [ss({"k": "yes"})])


def test_frequency_rejects_list_scores() -> None:
    with pytest.raises(TypeError, match="list-valued"):
        call(frequency(), [ss(["yes", "no"])])


def test_frequency_rejects_string_categories() -> None:
    with pytest.raises(TypeError, match="single string"):
        frequency(categories="yes")


def test_categorical_resolves_enum_to_list() -> None:
    from inspect_ai._util.registry import registry_params

    [m] = categorical(Verdict)
    assert registry_params(m)["categories"] == ["yes", "no", "unsure"]


def test_frequency_resolves_enum_to_list() -> None:
    from inspect_ai._util.registry import registry_params

    m = frequency(categories=Verdict)
    assert registry_params(m)["categories"] == ["yes", "no", "unsure"]


# ---------------------------------------------------------------------------
# @metric(scores=...) declaration
# ---------------------------------------------------------------------------


def test_frequency_declares_unreduced() -> None:
    assert metric_scores(frequency()) == "unreduced"


def test_metric_scores_default_reduced() -> None:
    assert metric_scores(accuracy()) == "auto"


def test_metric_scores_survives_metric_create() -> None:
    # the recompute path rebuilds metrics via metric_create()
    m = metric_create("frequency", categories=["yes", "no"])
    assert metric_scores(m) == "unreduced"
    m2 = metric_create("accuracy")
    assert metric_scores(m2) == "auto"


def test_metric_decorator_kwarg_only_scores() -> None:
    @metric(scores="unreduced")
    def my_metric() -> Metric:
        def compute(scores: list[SampleScore]) -> float:
            return float(len(scores))

        return compute

    assert metric_scores(my_metric()) == "unreduced"


# ---------------------------------------------------------------------------
# End-to-end round-trip: eval -> write -> read -> recompute
# ---------------------------------------------------------------------------


@scorer(metrics=categorical(Verdict))
def _verdict_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        idx = (hash((state.sample_id, state.epoch))) % 3
        return Score(value=list(Verdict)[idx])

    return score


@scorer(metrics=[frequency(categories=Verdict)])
def _verdict_frequency_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        idx = (hash((state.sample_id, state.epoch))) % 3
        return Score(value=list(Verdict)[idx])

    return score


@scorer(metrics=[accuracy(), frequency(categories=["C", "I"])])
def _mixed_correctness_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C" if state.epoch % 2 else "I")

    return score


@scorer(metrics=[frequency(categories=["C", "I"])])
def _frequency_correctness_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C" if state.epoch % 2 else "I")

    return score


@scorer(metrics={"*": [accuracy(), frequency(categories=["C", "I"])]})
def _dict_mixed_correctness_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        value = "C" if state.epoch % 2 else "I"
        return Score(value={"a": value, "b": "I" if value == "C" else "C"})

    return score


@scorer(metrics={"sab": categorical(Sabotage), "aware": categorical(Verdict)})
def _behaviour_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        idx = (hash((state.sample_id, state.epoch))) % 3
        return Score(
            value={"sab": list(Sabotage)[idx], "aware": list(Verdict)[(idx + 1) % 3]}
        )

    return score


def _metrics_snapshot(log) -> dict[str, dict[str, float]]:
    return {
        s.name: {k: round(v.value, 6) for k, v in s.metrics.items()}
        for s in log.results.scores
    }


def _score_by_reducer(log, name: str, reducer: str | None):
    assert log.results is not None
    return next(
        score
        for score in log.results.scores
        if score.name == name and score.reducer == reducer
    )


def test_mixed_metrics_use_reduced_and_unreduced_views() -> None:
    task = Task(
        dataset=[Sample(input="q")],
        scorer=_mixed_correctness_scorer(),
        epochs=2,
    )
    log = eval(task, model="mockllm/model", display="none")[0]

    reduced = _score_by_reducer(log, "_mixed_correctness_scorer", "mean")
    assert set(reduced.metrics) == {"accuracy"}
    assert reduced.metrics["accuracy"].value == pytest.approx(0.5)
    assert reduced.scored_samples == 1

    unreduced = _score_by_reducer(log, "_mixed_correctness_scorer", None)
    assert set(unreduced.metrics) == {"C", "I"}
    assert unreduced.metrics["C"].value == pytest.approx(0.5)
    assert unreduced.metrics["I"].value == pytest.approx(0.5)
    assert unreduced.scored_samples == 2


def test_frequency_uses_unreduced_view_with_explicit_reducer() -> None:
    task = Task(
        dataset=[Sample(input="q")],
        scorer=_frequency_correctness_scorer(),
        epochs=Epochs(2, "mode"),
    )
    log = eval(task, model="mockllm/model", display="none")[0]

    score = _score_by_reducer(log, "_frequency_correctness_scorer", None)
    assert set(score.metrics) == {"C", "I"}
    assert score.metrics["C"].value == pytest.approx(0.5)
    assert score.metrics["I"].value == pytest.approx(0.5)
    assert score.scored_samples == 2
    assert log.results is not None
    assert all(result.reducer != "mode" for result in log.results.scores)


def test_unreduced_metrics_run_once_with_multiple_reducers() -> None:
    task = Task(
        dataset=[Sample(input="q")],
        scorer=_mixed_correctness_scorer(),
        epochs=Epochs(2, ["mean", "max"]),
    )
    log = eval(task, model="mockllm/model", display="none")[0]

    mean_score = _score_by_reducer(log, "_mixed_correctness_scorer", "mean")
    max_score = _score_by_reducer(log, "_mixed_correctness_scorer", "max")
    frequency_score = _score_by_reducer(log, "_mixed_correctness_scorer", None)

    assert set(mean_score.metrics) == {"accuracy"}
    assert mean_score.metrics["accuracy"].value == pytest.approx(0.5)
    assert set(max_score.metrics) == {"accuracy"}
    assert max_score.metrics["accuracy"].value == pytest.approx(1.0)
    assert set(frequency_score.metrics) == {"C", "I"}
    assert frequency_score.metrics["C"].value == pytest.approx(0.5)
    assert frequency_score.metrics["I"].value == pytest.approx(0.5)


def test_no_reducer_preserves_auto_metric_unreduced_behavior() -> None:
    task = Task(
        dataset=[Sample(input="q")],
        scorer=_mixed_correctness_scorer(),
        epochs=Epochs(2, []),
    )
    log = eval(task, model="mockllm/model", display="none")[0]

    score = _score_by_reducer(log, "_mixed_correctness_scorer", None)
    assert set(score.metrics) == {"accuracy", "C", "I"}
    assert score.metrics["accuracy"].value == pytest.approx(0.5)
    assert score.metrics["C"].value == pytest.approx(0.5)
    assert score.metrics["I"].value == pytest.approx(0.5)
    assert score.scored_samples == 2


def test_no_reducer_rejects_explicit_reduced_metric_for_repeated_samples() -> None:
    from inspect_ai._eval.task.results import (
        ScorerInfo,
        compute_eval_scores_for_views,
    )

    @metric(scores="reduced")
    def reduced_count() -> Metric:
        def compute(scores: list[SampleScore]) -> float:
            return float(len(scores))

        return compute

    with pytest.raises(ValueError, match="epoch reduction is disabled"):
        compute_eval_scores_for_views(
            [
                SampleScore(sample_id=1, score=Score(value="C")),
                SampleScore(sample_id=1, score=Score(value="I")),
            ],
            [reduced_count()],
            "x",
            ScorerInfo(name="x", metrics=[reduced_count()]),
            [],
        )


def test_dict_mixed_metrics_use_reduced_and_unreduced_views() -> None:
    task = Task(
        dataset=[Sample(input="q")],
        scorer=_dict_mixed_correctness_scorer(),
        epochs=2,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]

        a_reduced = _score_by_reducer(log, "a", "mean")
        a_unreduced = _score_by_reducer(log, "a", None)
        assert set(a_reduced.metrics) == {"accuracy"}
        assert a_reduced.metrics["accuracy"].value == pytest.approx(0.5)
        assert set(a_unreduced.metrics) == {"frequency_C", "frequency_I"}
        assert a_unreduced.metrics["frequency_C"].value == pytest.approx(0.5)
        assert a_unreduced.metrics["frequency_I"].value == pytest.approx(0.5)

        before = [
            (s.name, s.reducer, {k: round(v.value, 6) for k, v in s.metrics.items()})
            for s in log.results.scores
        ]
        path = os.path.join(log_dir, "dict-mixed.eval")
        write_eval_log(log, path)
        reloaded = read_eval_log(path)
        recompute_metrics(reloaded)
        after = [
            (s.name, s.reducer, {k: round(v.value, 6) for k, v in s.metrics.items()})
            for s in reloaded.results.scores
        ]

    assert before == after


def test_categorical_recompute_round_trip() -> None:
    task = Task(
        dataset=[Sample(input=f"q{i}") for i in range(20)],
        scorer=[_verdict_scorer(), _behaviour_scorer()],
        epochs=3,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]
        assert log.status == "success"

        before = _metrics_snapshot(log)

        # all declared categories reported (including any zero-counts)
        assert log.results is not None
        verdict_score = next(
            s for s in log.results.scores if s.name == "_verdict_scorer"
        )
        assert set(verdict_score.metrics) == {"yes", "no", "unsure"}
        assert all(m.group == "frequency" for m in verdict_score.metrics.values())
        sab_score = next(s for s in log.results.scores if s.name == "sab")
        assert set(sab_score.metrics) == {
            "frequency_none",
            "frequency_subtle",
            "frequency_overt",
        }
        assert all(m.group == "frequency" for m in sab_score.metrics.values())

        # epochs were not reduced: 60 observations across 20 samples × 3 epochs
        assert log.reductions is None or all(
            r.reducer is None for r in log.reductions if r.scorer == "_verdict_scorer"
        )

        # round-trip through disk
        path = os.path.join(log_dir, "roundtrip.eval")
        write_eval_log(log, path)
        reloaded = read_eval_log(path)

        recompute_metrics(reloaded)
        after = _metrics_snapshot(reloaded)

    assert before == after


def test_frequency_strenum_recompute_round_trip() -> None:
    task = Task(
        dataset=[Sample(input=f"q{i}") for i in range(20)],
        scorer=_verdict_frequency_scorer(),
        epochs=3,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]
        assert log.status == "success"
        assert log.eval.scorers is not None
        metrics = log.eval.scorers[0].metrics
        assert isinstance(metrics, list)

        metric_def = metrics[0]
        assert not isinstance(metric_def, dict)
        assert metric_def.options is not None
        assert metric_def.options["categories"] == ["yes", "no", "unsure"]

        before = _metrics_snapshot(log)
        path = os.path.join(log_dir, "frequency-roundtrip.eval")
        write_eval_log(log, path)
        reloaded = read_eval_log(path)

        recompute_metrics(reloaded)
        after = _metrics_snapshot(reloaded)

    assert before == after


def test_score_rebuilds_eval_scorers_overwrite() -> None:
    from inspect_ai import score
    from inspect_ai.scorer import match

    task = Task(
        dataset=[Sample(input=f"q{i}", target="x") for i in range(8)],
        scorer=match(),
        epochs=2,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]
        assert log.eval.scorers is not None
        assert [s.name for s in log.eval.scorers] == ["match"]

        # re-score with a different (categorical) scorer, overwriting
        rescored = score(log, _verdict_scorer(), action="overwrite")
        assert rescored.eval.scorers is not None
        assert [s.name for s in rescored.eval.scorers] == ["_verdict_scorer"]

        before = _metrics_snapshot(rescored)
        assert set(before["_verdict_scorer"]) == {"yes", "no", "unsure"}

        # round-trip through disk then recompute
        path = os.path.join(log_dir, "rescored.eval")
        write_eval_log(rescored, path)
        reloaded = read_eval_log(path)
        recompute_metrics(reloaded)
        assert _metrics_snapshot(reloaded) == before


def test_score_rebuilds_eval_scorers_append() -> None:
    from inspect_ai import score
    from inspect_ai.scorer import match

    task = Task(
        dataset=[Sample(input=f"q{i}", target="x") for i in range(8)],
        scorer=_verdict_scorer(),
        epochs=2,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]
        assert log.eval.scorers is not None
        assert [s.name for s in log.eval.scorers] == ["_verdict_scorer"]

        # append a numeric scorer; original categorical scorer must survive
        rescored = score(log, match(), action="append")
        assert rescored.eval.scorers is not None
        assert [s.name for s in rescored.eval.scorers] == ["_verdict_scorer", "match"]

        before = _metrics_snapshot(rescored)
        path = os.path.join(log_dir, "rescored.eval")
        write_eval_log(rescored, path)
        reloaded = read_eval_log(path)
        recompute_metrics(reloaded)
        assert _metrics_snapshot(reloaded) == before


def test_score_append_duplicate_scorer_recompute_round_trip() -> None:
    from inspect_ai import score
    from inspect_ai.scorer import match

    task = Task(
        dataset=[Sample(input=f"q{i}", target="x") for i in range(8)],
        scorer=match(),
        epochs=2,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]

        rescored = score(log, match(), action="append")
        assert rescored.eval.scorers is not None
        assert [s.name for s in rescored.eval.scorers] == ["match", "match"]
        assert rescored.results is not None
        assert [s.name for s in rescored.results.scores] == ["match", "match1"]

        before = _metrics_snapshot(rescored)
        path = os.path.join(log_dir, "rescored.eval")
        write_eval_log(rescored, path)
        reloaded = read_eval_log(path)
        recompute_metrics(reloaded)

    assert reloaded.results is not None
    assert [s.name for s in reloaded.results.scores] == ["match", "match1"]
    assert _metrics_snapshot(reloaded) == before


def test_score_repeated_append_same_scorer_recompute_round_trip() -> None:
    from inspect_ai import score
    from inspect_ai.scorer import match

    task = Task(
        dataset=[Sample(input=f"q{i}", target="x") for i in range(8)],
        scorer=match(),
        epochs=2,
    )
    with tempfile.TemporaryDirectory() as log_dir:
        log = eval(task, model="mockllm/model", log_dir=log_dir, display="none")[0]

        # appending the same scorer multiple times grows the header in lockstep
        # with the (disambiguated) result scores; recompute_metrics re-derives the
        # same unique names from the header, so the round-trip is preserved.
        rescored = score(log, match(), action="append")
        rescored = score(rescored, match(), action="append")
        assert rescored.eval.scorers is not None
        assert [s.name for s in rescored.eval.scorers] == ["match", "match", "match"]
        assert rescored.results is not None
        assert [s.name for s in rescored.results.scores] == ["match", "match1", "match2"]
        assert all(s.scored_samples == 8 for s in rescored.results.scores)

        before = _metrics_snapshot(rescored)
        path = os.path.join(log_dir, "rescored.eval")
        write_eval_log(rescored, path)
        reloaded = read_eval_log(path)
        recompute_metrics(reloaded)

    assert reloaded.results is not None
    assert [s.name for s in reloaded.results.scores] == ["match", "match1", "match2"]
    assert all(s.scored_samples == 8 for s in reloaded.results.scores)
    assert _metrics_snapshot(reloaded) == before
