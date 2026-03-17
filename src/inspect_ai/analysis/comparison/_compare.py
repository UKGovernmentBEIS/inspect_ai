"""Core comparison logic for evaluation runs.

Loads two eval logs, aligns samples, computes score deltas,
runs significance tests, and returns a structured ComparisonResult.
"""

from __future__ import annotations

from collections.abc import Callable
from logging import getLogger
from math import isfinite
from pathlib import Path
from typing import Literal

from inspect_ai.analysis.comparison._alignment import AlignedSample, align_samples
from inspect_ai.analysis.comparison._statistics import (
    bootstrap_ci,
    cohens_d,
    mcnemars_test,
)
from inspect_ai.analysis.comparison._types import (
    ComparisonResult,
    MetricComparison,
    SampleComparison,
)
from inspect_ai.log._file import read_eval_log
from inspect_ai.log._log import EvalLog, EvalSample
from inspect_ai.scorer._metric import value_to_float

logger = getLogger(__name__)

_to_float = value_to_float()


def compare_evals(
    baseline: str | Path | EvalLog,
    candidate: str | Path | EvalLog,
    scorers: list[str] | None = None,
    significance: float = 0.05,
    regression_threshold: float = 0.0,
    sample_filter: Callable[[EvalSample], bool] | None = None,
) -> ComparisonResult:
    """Compare results from two evaluation runs.

    Loads both logs, aligns samples by (id, epoch), computes score
    deltas and aggregate metric differences, and runs significance
    tests on the differences.

    Args:
        baseline: Path to baseline eval log, or an EvalLog object.
        candidate: Path to candidate eval log, or an EvalLog object.
        scorers: Specific scorer names to compare. None compares all.
        significance: P-value threshold for significance tests.
        regression_threshold: Minimum absolute delta to count as
            regression or improvement. Deltas within this threshold
            are classified as unchanged. Default 0.0 (any difference counts).
        sample_filter: Optional function to filter samples before comparison.
            Only samples where filter returns True are included.

    Returns:
        ComparisonResult with metrics, sample comparisons, and regressions.
    """
    baseline_log = _load_log(baseline)
    candidate_log = _load_log(candidate)

    # Apply sample filter if provided
    if sample_filter is not None:
        baseline_log = _filter_samples(baseline_log, sample_filter)
        candidate_log = _filter_samples(candidate_log, sample_filter)

    baseline_path = _log_path(baseline, baseline_log)
    candidate_path = _log_path(candidate, candidate_log)

    baseline_task = baseline_log.eval.task
    candidate_task = candidate_log.eval.task
    baseline_model = baseline_log.eval.model
    candidate_model = candidate_log.eval.model

    scorer_names = _resolve_scorers(baseline_log, candidate_log, scorers)
    aligned = align_samples(baseline_log, candidate_log)
    sample_comparisons = _compare_samples(aligned, scorer_names, regression_threshold)
    metric_comparisons = _compare_metrics(
        baseline_log, candidate_log, scorer_names, aligned, significance
    )

    return ComparisonResult(
        baseline_log=baseline_path,
        candidate_log=candidate_path,
        baseline_task=baseline_task,
        candidate_task=candidate_task,
        baseline_model=baseline_model,
        candidate_model=candidate_model,
        metrics=metric_comparisons,
        samples=sample_comparisons,
    )


def _load_log(source: str | Path | EvalLog) -> EvalLog:
    """Load an eval log from path or return as-is if already loaded."""
    if isinstance(source, EvalLog):
        return source
    return read_eval_log(str(source))


def _log_path(source: str | Path | EvalLog, log: EvalLog) -> str:
    """Get a display path for the log."""
    if isinstance(source, (str, Path)):
        return str(source)
    return log.location or "unknown"


def _filter_samples(log: EvalLog, fn: Callable[[EvalSample], bool]) -> EvalLog:
    """Return a copy of the log with only samples passing the filter."""
    if log.samples is None:
        return log
    filtered = [s for s in log.samples if fn(s)]
    # Create a shallow copy with filtered samples
    return log.model_copy(update={"samples": filtered})


def _resolve_scorers(
    baseline_log: EvalLog,
    candidate_log: EvalLog,
    requested: list[str] | None,
) -> list[str]:
    """Determine which scorers to compare.

    If requested is None, returns the intersection of scorers
    present in both logs.
    """
    baseline_scorers = _get_scorer_names(baseline_log)
    candidate_scorers = _get_scorer_names(candidate_log)

    if requested is not None:
        missing_baseline = set(requested) - baseline_scorers
        missing_candidate = set(requested) - candidate_scorers
        if missing_baseline:
            logger.warning("Scorers not in baseline: %s", missing_baseline)
        if missing_candidate:
            logger.warning("Scorers not in candidate: %s", missing_candidate)
        return [
            s for s in requested if s in baseline_scorers and s in candidate_scorers
        ]

    common = baseline_scorers & candidate_scorers
    if not common:
        logger.warning(
            "No common scorers between logs. Baseline: %s, Candidate: %s",
            baseline_scorers,
            candidate_scorers,
        )
    return sorted(common)


def _get_scorer_names(log: EvalLog) -> set[str]:
    """Extract scorer names from an eval log."""
    names: set[str] = set()
    if log.results and log.results.scores:
        for score_entry in log.results.scores:
            names.add(score_entry.name)
    if log.samples:
        for sample in log.samples:
            if sample.scores:
                names.update(sample.scores.keys())
    return names


def _compare_samples(
    aligned: list[AlignedSample],
    scorer_names: list[str],
    regression_threshold: float = 0.0,
) -> list[SampleComparison]:
    """Compare per-sample scores across aligned pairs."""
    comparisons: list[SampleComparison] = []

    for pair in aligned:
        for scorer in scorer_names:
            bl_score = _extract_score(pair.baseline, scorer)
            cd_score = _extract_score(pair.candidate, scorer)

            direction: Literal["improved", "regressed", "unchanged", "new", "missing"]
            if pair.baseline is None:
                direction = "new"
                delta = None
            elif pair.candidate is None:
                direction = "missing"
                delta = None
            elif bl_score is not None and cd_score is not None:
                delta = cd_score - bl_score
                if abs(delta) <= regression_threshold:
                    direction = "unchanged"
                elif delta > 0:
                    direction = "improved"
                else:
                    direction = "regressed"
            else:
                direction = "unchanged"
                delta = None

            comparisons.append(
                SampleComparison(
                    id=pair.id,
                    epoch=pair.epoch,
                    scorer=scorer,
                    baseline_score=bl_score,
                    candidate_score=cd_score,
                    delta=delta,
                    direction=direction,
                )
            )

    return comparisons


def _compare_metrics(
    baseline_log: EvalLog,
    candidate_log: EvalLog,
    scorer_names: list[str],
    aligned: list[AlignedSample],
    significance: float,
) -> list[MetricComparison]:
    """Compare aggregate metrics and run significance tests."""
    comparisons: list[MetricComparison] = []

    baseline_metrics = _extract_metrics(baseline_log)
    candidate_metrics = _extract_metrics(candidate_log)

    for scorer in scorer_names:
        bl_scorer_metrics = baseline_metrics.get(scorer, {})
        cd_scorer_metrics = candidate_metrics.get(scorer, {})

        common_metrics = set(bl_scorer_metrics.keys()) & set(cd_scorer_metrics.keys())

        bl_scores, cd_scores = _collect_paired_scores(aligned, scorer)

        # Run significance test
        sig_result = None
        if bl_scores and cd_scores:
            all_binary = all(v in (0.0, 1.0) for v in bl_scores + cd_scores)
            if all_binary:
                sig_result = mcnemars_test(
                    [v == 1.0 for v in bl_scores],
                    [v == 1.0 for v in cd_scores],
                    significance=significance,
                )
            else:
                sig_result = bootstrap_ci(
                    bl_scores, cd_scores, significance=significance
                )

        # Compute effect size
        effect = cohens_d(bl_scores, cd_scores) if bl_scores and cd_scores else None

        # Significance test applies only to primary metrics (accuracy, mean).
        # Other metrics (stderr, etc.) report delta but no significance result
        # since the test was not run on their specific values.
        primary_metrics = {"accuracy", "mean"}

        for metric_name in sorted(common_metrics):
            bl_val = bl_scorer_metrics[metric_name]
            cd_val = cd_scorer_metrics[metric_name]
            delta = cd_val - bl_val
            rel_delta = delta / bl_val if bl_val != 0 else None

            is_primary = metric_name in primary_metrics
            comparisons.append(
                MetricComparison(
                    name=metric_name,
                    scorer=scorer,
                    baseline_value=bl_val,
                    candidate_value=cd_val,
                    delta=delta,
                    relative_delta=rel_delta,
                    significant=(
                        sig_result.significant if sig_result and is_primary else False
                    ),
                    p_value=sig_result.p_value if sig_result and is_primary else None,
                    ci_lower=sig_result.ci_lower if sig_result and is_primary else None,
                    ci_upper=sig_result.ci_upper if sig_result and is_primary else None,
                    effect_size=effect if is_primary else None,
                )
            )

    return comparisons


def _extract_metrics(log: EvalLog) -> dict[str, dict[str, float]]:
    """Extract {scorer: {metric_name: value}} from log results."""
    result: dict[str, dict[str, float]] = {}
    if log.results and log.results.scores:
        for score_entry in log.results.scores:
            metrics: dict[str, float] = {}
            if score_entry.metrics:
                for metric_name, metric_val in score_entry.metrics.items():
                    val = metric_val.value
                    if isinstance(val, (int, float)):
                        metrics[metric_name] = float(val)
            result[score_entry.name] = metrics
    return result


def _extract_score(sample: EvalSample | None, scorer: str) -> float | None:
    """Extract a numeric score from a sample for a given scorer."""
    if sample is None or sample.scores is None:
        return None
    score = sample.scores.get(scorer)
    if score is None:
        return None
    if isinstance(score.value, (dict, list)):
        return None
    try:
        val = _to_float(score.value)
        if not isfinite(val):
            return None
        return val
    except (ValueError, TypeError):
        return None


def _collect_paired_scores(
    aligned: list[AlignedSample],
    scorer: str,
) -> tuple[list[float], list[float]]:
    """Collect paired score lists for samples present in both runs."""
    bl_scores: list[float] = []
    cd_scores: list[float] = []

    for pair in aligned:
        if pair.baseline is None or pair.candidate is None:
            continue
        bl_val = _extract_score(pair.baseline, scorer)
        cd_val = _extract_score(pair.candidate, scorer)
        if bl_val is not None and cd_val is not None:
            bl_scores.append(bl_val)
            cd_scores.append(cd_val)

    return bl_scores, cd_scores
