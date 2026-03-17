"""Tests for evaluation comparison framework."""

from __future__ import annotations

import pytest

from inspect_ai.analysis.comparison._alignment import AlignedSample, align_samples
from inspect_ai.analysis.comparison._compare import (
    _compare_samples,
    _extract_score,
    compare_evals,
)
from inspect_ai.analysis.comparison._statistics import (
    bootstrap_ci,
    cohens_d,
    mcnemars_test,
    permutation_test,
)
from inspect_ai.analysis.comparison._types import ComparisonResult
from inspect_ai.log import (
    EvalLog,
    EvalMetric,
    EvalResults,
    EvalSample,
    EvalScore,
    EvalSpec,
)
from inspect_ai.log._log import EvalConfig, EvalDataset
from inspect_ai.scorer import Score


def _make_sample(
    id: int | str,
    epoch: int = 1,
    scores: dict[str, str | float] | None = None,
) -> EvalSample:
    """Create a minimal EvalSample for testing."""
    score_dict = None
    if scores:
        score_dict = {name: Score(value=val) for name, val in scores.items()}
    return EvalSample(
        id=id,
        epoch=epoch,
        input=f"input_{id}",
        target=f"target_{id}",
        scores=score_dict,
    )


def _make_eval_log(
    task: str = "test_task",
    model: str = "test/model",
    samples: list[EvalSample] | None = None,
    scores: list[EvalScore] | None = None,
) -> EvalLog:
    """Create a minimal EvalLog for testing."""
    results = None
    if scores:
        results = EvalResults(
            total_samples=len(samples) if samples else 0,
            completed_samples=len(samples) if samples else 0,
            scores=scores,
        )

    return EvalLog(
        version=2,
        status="success",
        eval=EvalSpec(
            task=task,
            model=model,
            created="2026-01-01T00:00:00Z",
            dataset=EvalDataset(name="test"),
            config=EvalConfig(),
        ),
        results=results,
        samples=samples,
    )


def test_align_identical_samples():
    """Samples with matching (id, epoch) align correctly."""
    baseline = _make_eval_log(
        samples=[
            _make_sample(1, scores={"acc": "C"}),
            _make_sample(2, scores={"acc": "I"}),
            _make_sample(3, scores={"acc": "C"}),
        ]
    )
    candidate = _make_eval_log(
        samples=[
            _make_sample(1, scores={"acc": "C"}),
            _make_sample(2, scores={"acc": "C"}),
            _make_sample(3, scores={"acc": "I"}),
        ]
    )

    aligned = align_samples(baseline, candidate)
    assert len(aligned) == 3
    assert all(a.baseline is not None and a.candidate is not None for a in aligned)


def test_align_missing_samples():
    """Samples in baseline but not candidate are marked as missing."""
    baseline = _make_eval_log(
        samples=[
            _make_sample(1),
            _make_sample(2),
            _make_sample(3),
        ]
    )
    candidate = _make_eval_log(
        samples=[
            _make_sample(1),
            _make_sample(3),
        ]
    )

    aligned = align_samples(baseline, candidate)
    assert len(aligned) == 3

    missing = [a for a in aligned if a.candidate is None]
    assert len(missing) == 1
    assert missing[0].id == 2


def test_align_new_samples():
    """Samples in candidate but not baseline are marked as new."""
    baseline = _make_eval_log(samples=[_make_sample(1)])
    candidate = _make_eval_log(samples=[_make_sample(1), _make_sample(2)])

    aligned = align_samples(baseline, candidate)
    assert len(aligned) == 2

    new = [a for a in aligned if a.baseline is None]
    assert len(new) == 1
    assert new[0].id == 2


def test_align_string_int_id_normalization():
    """String '1' and int 1 should align as the same sample."""
    baseline = _make_eval_log(samples=[_make_sample("1", scores={"acc": "C"})])
    candidate = _make_eval_log(samples=[_make_sample(1, scores={"acc": "I"})])

    aligned = align_samples(baseline, candidate)
    assert len(aligned) == 1
    assert aligned[0].baseline is not None
    assert aligned[0].candidate is not None


def test_align_multi_epoch():
    """Samples with different epochs are treated as distinct."""
    baseline = _make_eval_log(
        samples=[
            _make_sample(1, epoch=1, scores={"acc": "C"}),
            _make_sample(1, epoch=2, scores={"acc": "I"}),
        ]
    )
    candidate = _make_eval_log(
        samples=[
            _make_sample(1, epoch=1, scores={"acc": "I"}),
            _make_sample(1, epoch=2, scores={"acc": "C"}),
        ]
    )

    aligned = align_samples(baseline, candidate)
    assert len(aligned) == 2


def test_align_empty_logs():
    """Empty sample lists produce empty alignment."""
    baseline = _make_eval_log(samples=[])
    candidate = _make_eval_log(samples=[])

    aligned = align_samples(baseline, candidate)
    assert len(aligned) == 0


# Score extraction


def test_extract_score_correct():
    sample = _make_sample(1, scores={"acc": "C"})
    assert _extract_score(sample, "acc") == 1.0


def test_extract_score_incorrect():
    sample = _make_sample(1, scores={"acc": "I"})
    assert _extract_score(sample, "acc") == 0.0


def test_extract_score_float():
    sample = _make_sample(1, scores={"f1": 0.85})
    assert _extract_score(sample, "f1") == 0.85


def test_extract_score_missing_scorer():
    sample = _make_sample(1, scores={"acc": "C"})
    assert _extract_score(sample, "nonexistent") is None


def test_extract_score_none_sample():
    assert _extract_score(None, "acc") is None


# Sample comparison


def test_compare_samples_regression():
    """Detect when candidate scores lower than baseline."""
    aligned = [
        AlignedSample(
            id=1,
            epoch=1,
            baseline=_make_sample(1, scores={"acc": "C"}),
            candidate=_make_sample(1, scores={"acc": "I"}),
        ),
    ]
    comparisons = _compare_samples(aligned, ["acc"])
    assert len(comparisons) == 1
    assert comparisons[0].direction == "regressed"
    assert comparisons[0].delta == -1.0


def test_compare_samples_improvement():
    """Detect when candidate scores higher than baseline."""
    aligned = [
        AlignedSample(
            id=1,
            epoch=1,
            baseline=_make_sample(1, scores={"acc": "I"}),
            candidate=_make_sample(1, scores={"acc": "C"}),
        ),
    ]
    comparisons = _compare_samples(aligned, ["acc"])
    assert len(comparisons) == 1
    assert comparisons[0].direction == "improved"
    assert comparisons[0].delta == 1.0


def test_compare_samples_unchanged():
    """Detect when scores are identical."""
    aligned = [
        AlignedSample(
            id=1,
            epoch=1,
            baseline=_make_sample(1, scores={"acc": "C"}),
            candidate=_make_sample(1, scores={"acc": "C"}),
        ),
    ]
    comparisons = _compare_samples(aligned, ["acc"])
    assert comparisons[0].direction == "unchanged"
    assert comparisons[0].delta == 0.0


def test_compare_samples_multi_scorer():
    """Compare across multiple scorers per sample."""
    aligned = [
        AlignedSample(
            id=1,
            epoch=1,
            baseline=_make_sample(1, scores={"acc": "C", "f1": 0.9}),
            candidate=_make_sample(1, scores={"acc": "I", "f1": 0.95}),
        ),
    ]
    comparisons = _compare_samples(aligned, ["acc", "f1"])
    assert len(comparisons) == 2

    acc = next(c for c in comparisons if c.scorer == "acc")
    f1 = next(c for c in comparisons if c.scorer == "f1")
    assert acc.direction == "regressed"
    assert f1.direction == "improved"


# Statistical tests


def test_bootstrap_ci_significant():
    """Bootstrap CI detects significant difference."""
    baseline = [0.0] * 50 + [1.0] * 50
    candidate = [0.0] * 30 + [1.0] * 70

    result = bootstrap_ci(baseline, candidate, significance=0.05)
    assert result.significant
    assert result.p_value < 0.05
    assert result.ci_lower > 0  # difference is positive


def test_bootstrap_ci_not_significant():
    """Bootstrap CI correctly identifies no significant difference."""
    baseline = [0.0] * 48 + [1.0] * 52
    candidate = [0.0] * 47 + [1.0] * 53

    result = bootstrap_ci(baseline, candidate, significance=0.05)
    assert not result.significant


def test_bootstrap_ci_empty():
    """Empty inputs return non-significant result."""
    result = bootstrap_ci([], [], significance=0.05)
    assert not result.significant
    assert result.p_value == 1.0


def test_mcnemar_significant():
    """McNemar's test detects significant asymmetry in discordant pairs."""
    # 30 samples where baseline got right but candidate got wrong
    # 5 samples where candidate got right but baseline got wrong
    baseline_correct = [True] * 30 + [False] * 5 + [True] * 65
    candidate_correct = [False] * 30 + [True] * 5 + [True] * 65

    result = mcnemars_test(baseline_correct, candidate_correct, significance=0.05)
    assert result.significant
    assert result.p_value < 0.05


def test_mcnemar_not_significant():
    """McNemar's test with balanced discordant pairs is not significant."""
    baseline_correct = [True] * 10 + [False] * 10 + [True] * 80
    candidate_correct = [False] * 10 + [True] * 10 + [True] * 80

    result = mcnemars_test(baseline_correct, candidate_correct, significance=0.05)
    assert not result.significant


def test_mcnemar_empty():
    result = mcnemars_test([], [], significance=0.05)
    assert not result.significant


def test_mcnemar_no_discordant():
    """All samples agree between runs."""
    baseline_correct = [True, True, False, False]
    candidate_correct = [True, True, False, False]

    result = mcnemars_test(baseline_correct, candidate_correct)
    assert not result.significant
    assert result.p_value == 1.0


def test_permutation_significant():
    """Permutation test detects significant difference."""
    baseline = [0.0] * 50 + [1.0] * 50
    candidate = [0.0] * 20 + [1.0] * 80

    result = permutation_test(baseline, candidate, significance=0.05, n_iterations=5000)
    assert result.significant


def test_permutation_empty():
    result = permutation_test([], [], significance=0.05)
    assert not result.significant


# Integration tests


def test_compare_evals_full():
    """Full comparison with metrics and sample-level details."""
    baseline = _make_eval_log(
        task="math",
        model="gpt-4o",
        samples=[
            _make_sample(1, scores={"match": "C"}),
            _make_sample(2, scores={"match": "C"}),
            _make_sample(3, scores={"match": "I"}),
            _make_sample(4, scores={"match": "C"}),
            _make_sample(5, scores={"match": "I"}),
        ],
        scores=[
            EvalScore(
                name="match",
                scorer="match",
                params={},
                metrics={"accuracy": EvalMetric(name="accuracy", value=0.6, params={})},
            ),
        ],
    )
    candidate = _make_eval_log(
        task="math",
        model="claude-sonnet",
        samples=[
            _make_sample(1, scores={"match": "C"}),
            _make_sample(2, scores={"match": "I"}),
            _make_sample(3, scores={"match": "C"}),
            _make_sample(4, scores={"match": "C"}),
            _make_sample(5, scores={"match": "C"}),
        ],
        scores=[
            EvalScore(
                name="match",
                scorer="match",
                params={},
                metrics={"accuracy": EvalMetric(name="accuracy", value=0.8, params={})},
            ),
        ],
    )

    result = compare_evals(baseline, candidate)

    assert isinstance(result, ComparisonResult)
    assert result.baseline_model == "gpt-4o"
    assert result.candidate_model == "claude-sonnet"

    # Metric comparison
    assert len(result.metrics) == 1
    assert result.metrics[0].name == "accuracy"
    assert result.metrics[0].delta == pytest.approx(0.2)

    # Sample counts
    assert result.aligned_count == 5
    assert result.missing_count == 0
    assert result.new_count == 0

    # 1 regression (sample 2: C -> I), 2 improvements (3: I->C, 5: I->C)
    assert len(result.regressions) == 1
    assert result.regressions[0].id == 2
    assert len(result.improvements) == 2
    assert len(result.unchanged) == 2

    # Summary text
    summary = result.summary()
    assert "gpt-4o" in summary
    assert "claude-sonnet" in summary


def test_compare_evals_no_common_scorers():
    """Logs with different scorers produce empty comparison."""
    baseline = _make_eval_log(samples=[_make_sample(1, scores={"acc": "C"})])
    candidate = _make_eval_log(samples=[_make_sample(1, scores={"f1": 0.9})])

    result = compare_evals(baseline, candidate)
    assert len(result.metrics) == 0
    assert len(result.samples) == 0


def test_compare_evals_specific_scorer():
    """Filter comparison to specific scorers."""
    baseline = _make_eval_log(samples=[_make_sample(1, scores={"acc": "C", "f1": 0.9})])
    candidate = _make_eval_log(
        samples=[_make_sample(1, scores={"acc": "I", "f1": 0.95})]
    )

    result = compare_evals(baseline, candidate, scorers=["f1"])
    assert len(result.samples) == 1
    assert result.samples[0].scorer == "f1"
    assert result.samples[0].direction == "improved"


# Effect size


def test_cohens_d_large_effect():
    baseline = [0.0] * 50 + [1.0] * 50
    candidate = [0.0] * 20 + [1.0] * 80
    d = cohens_d(baseline, candidate)
    assert d is not None
    assert d > 0.5


def test_cohens_d_zero_effect():
    scores = [0.5] * 100
    d = cohens_d(scores, scores)
    assert d == 0.0


def test_cohens_d_too_few_samples():
    assert cohens_d([1.0], [0.0]) is None


def test_effect_size_in_metric_comparison():
    baseline = _make_eval_log(
        model="model-a",
        samples=[
            _make_sample(i, scores={"acc": "C" if i % 2 == 0 else "I"})
            for i in range(20)
        ],
        scores=[
            EvalScore(
                name="acc",
                scorer="acc",
                params={},
                metrics={"accuracy": EvalMetric(name="accuracy", value=0.5, params={})},
            ),
        ],
    )
    candidate = _make_eval_log(
        model="model-b",
        samples=[
            _make_sample(i, scores={"acc": "C" if i % 3 != 0 else "I"})
            for i in range(20)
        ],
        scores=[
            EvalScore(
                name="acc",
                scorer="acc",
                params={},
                metrics={
                    "accuracy": EvalMetric(name="accuracy", value=0.65, params={})
                },
            ),
        ],
    )
    result = compare_evals(baseline, candidate)
    acc_metric = next(m for m in result.metrics if m.name == "accuracy")
    assert acc_metric.effect_size is not None


# Win rate


def test_win_rate():
    baseline = _make_eval_log(
        samples=[
            _make_sample(1, scores={"acc": "C"}),
            _make_sample(2, scores={"acc": "C"}),
            _make_sample(3, scores={"acc": "I"}),
            _make_sample(4, scores={"acc": "I"}),
        ]
    )
    candidate = _make_eval_log(
        samples=[
            _make_sample(1, scores={"acc": "I"}),
            _make_sample(2, scores={"acc": "C"}),
            _make_sample(3, scores={"acc": "C"}),
            _make_sample(4, scores={"acc": "C"}),
        ]
    )
    result = compare_evals(baseline, candidate)
    assert result.win_rate == pytest.approx(0.5)


def test_win_rate_empty():
    baseline = _make_eval_log(samples=[])
    candidate = _make_eval_log(samples=[])
    result = compare_evals(baseline, candidate)
    assert result.win_rate is None


# Regression threshold


def test_regression_threshold_filters_noise():
    baseline = _make_eval_log(samples=[_make_sample(1, scores={"f1": 0.80})])
    candidate = _make_eval_log(samples=[_make_sample(1, scores={"f1": 0.79})])

    result_strict = compare_evals(baseline, candidate, regression_threshold=0.0)
    assert result_strict.samples[0].direction == "regressed"

    result_tolerant = compare_evals(baseline, candidate, regression_threshold=0.02)
    assert result_tolerant.samples[0].direction == "unchanged"


# Sample filter


def test_sample_filter():
    baseline = _make_eval_log(
        samples=[
            _make_sample(1, scores={"acc": "C"}),
            _make_sample(2, scores={"acc": "I"}),
            _make_sample(3, scores={"acc": "C"}),
        ]
    )
    candidate = _make_eval_log(
        samples=[
            _make_sample(1, scores={"acc": "I"}),
            _make_sample(2, scores={"acc": "C"}),
            _make_sample(3, scores={"acc": "C"}),
        ]
    )

    result = compare_evals(
        baseline,
        candidate,
        sample_filter=lambda s: s.id in (1, 2),
    )
    assert result.aligned_count == 2
    assert len(result.regressions) == 1
    assert result.regressions[0].id == 1


# NaN and non-finite score handling


def test_nan_score_excluded():
    baseline = _make_eval_log(samples=[_make_sample(1, scores={"acc": float("nan")})])
    candidate = _make_eval_log(samples=[_make_sample(1, scores={"acc": "C"})])
    result = compare_evals(baseline, candidate)
    assert result.samples[0].baseline_score is None
    assert result.samples[0].direction == "unchanged"


def test_dict_score_excluded():
    baseline = _make_eval_log(
        samples=[
            _make_sample(1, scores={"multi": {"rouge1": 0.8, "rouge2": 0.6}}),
        ]
    )
    candidate = _make_eval_log(
        samples=[
            _make_sample(1, scores={"multi": {"rouge1": 0.9, "rouge2": 0.7}}),
        ]
    )
    result = compare_evals(baseline, candidate)
    assert result.samples[0].baseline_score is None
    assert result.samples[0].candidate_score is None
