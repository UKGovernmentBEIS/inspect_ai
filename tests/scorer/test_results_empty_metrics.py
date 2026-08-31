"""Results-level: zero scored samples attempt-calls the metric (#5150)."""

import math

from inspect_ai._eval.task.results import ScorerInfo, scorers_from_metric_dict
from inspect_ai.scorer import Score, accuracy, grouped, mean
from inspect_ai.scorer._metric import SampleScore


def _unscored(n: int = 3):
    return [
        SampleScore(score=Score(value=float("nan")), sample_metadata={"group": "A"})
        for _ in range(n)
    ]


def test_all_unscored_grouped_reports_shaped_aggregate_key():
    metric = grouped(mean(), group_key="group")
    results = scorers_from_metric_dict(
        scorer_name="test_scorer",
        scorer_info=ScorerInfo(name="test_scorer", metrics={"score": [metric]}),
        sample_scores=_unscored(),
        metrics={"score": [metric]},
    )
    metrics = results[0].metrics
    # The degenerate shape survives: aggregate key present, not a bare flat NaN row.
    all_metrics = [m for m in metrics.values() if m.name == "all"]
    assert len(all_metrics) == 1
    assert math.isnan(all_metrics[0].value)


def test_all_unscored_scalar_metric_still_flat_nan():
    metric = accuracy()
    results = scorers_from_metric_dict(
        scorer_name="test_scorer",
        scorer_info=ScorerInfo(name="test_scorer", metrics={"score": [metric]}),
        sample_scores=_unscored(),
        metrics={"score": [metric]},
    )
    metrics = results[0].metrics
    assert len(metrics) == 1
    only = next(iter(metrics.values()))
    assert math.isnan(only.value)
