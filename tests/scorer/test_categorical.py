import os
import tempfile
from typing import cast

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log, recompute_metrics, write_eval_log
from inspect_ai.scorer import (
    Metric,
    Score,
    Scorer,
    StrEnum,
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
    assert metric_scores(accuracy()) == "reduced"


def test_metric_scores_survives_metric_create() -> None:
    # the recompute path rebuilds metrics via metric_create()
    m = metric_create("frequency", categories=["yes", "no"])
    assert metric_scores(m) == "unreduced"
    m2 = metric_create("accuracy")
    assert metric_scores(m2) == "reduced"


def test_metric_decorator_kwarg_only_scores() -> None:
    @metric(scores="unreduced")
    def my_metric() -> Metric:
        def compute(scores: list[SampleScore]) -> float:
            return float(len(scores))

        return compute

    assert metric_scores(my_metric()) == "unreduced"


def test_resolve_reducer_skips_for_unreduced_metric() -> None:
    from inspect_ai._eval.task.results import ScorerInfo, resolve_reducer

    info = ScorerInfo(name="x", metrics=[*categorical(Verdict)])
    reducers, named = resolve_reducer(None, info)
    assert reducers == []
    assert named is False


def test_resolve_reducer_defaults_mean_for_reduced_metric() -> None:
    from inspect_ai._eval.task.results import ScorerInfo, resolve_reducer

    info = ScorerInfo(name="x", metrics=[accuracy()])
    reducers, named = resolve_reducer(None, info)
    assert len(reducers) == 1
    assert named is False


def test_resolve_reducer_explicit_reducer_honoured() -> None:
    from inspect_ai._eval.task.results import ScorerInfo, resolve_reducer
    from inspect_ai.scorer import mode_score

    info = ScorerInfo(name="x", metrics=[*categorical(Verdict)])
    reducers, named = resolve_reducer([mode_score()], info)
    assert len(reducers) == 1
    assert named is True


def test_resolve_reducer_mixed_modes_warns_and_uses_unreduced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from inspect_ai._eval.task.results import ScorerInfo, resolve_reducer

    info = ScorerInfo(name="x", metrics=[accuracy(), frequency(categories=Verdict)])
    with caplog.at_level(logging.WARNING):
        reducers, _ = resolve_reducer(None, info)
    assert reducers == []
    assert any("mixed" in r.message for r in caplog.records)


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
