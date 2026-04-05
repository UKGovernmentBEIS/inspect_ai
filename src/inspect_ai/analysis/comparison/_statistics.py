"""Statistical tests for evaluation comparison.

Provides bootstrap confidence intervals, McNemar's test for paired
binary outcomes, permutation tests, and effect size. Uses NumPy only
(no scipy dependency).
"""

from __future__ import annotations

from dataclasses import dataclass
from logging import getLogger
from math import erfc, sqrt
from math import log as _log

import numpy as np

logger = getLogger(__name__)

_BOOTSTRAP_RESAMPLES = 10_000
_PERMUTATION_ITERATIONS = 10_000
_BATCH_SIZE = 1000


@dataclass
class SignificanceResult:
    """Result of a statistical significance test."""

    significant: bool
    """Whether the difference is significant at the given level."""

    p_value: float
    """Computed p-value."""

    ci_lower: float
    """Lower bound of confidence interval for the difference."""

    ci_upper: float
    """Upper bound of confidence interval for the difference."""

    method: str
    """Name of the test used."""


def bootstrap_ci(
    baseline_scores: list[float],
    candidate_scores: list[float],
    significance: float = 0.05,
    n_resamples: int = _BOOTSTRAP_RESAMPLES,
    seed: int | None = 42,
) -> SignificanceResult:
    """Compute bootstrap confidence interval for the difference in means.

    Uses the shifted bootstrap (centered under H0) for proper two-sided
    p-value computation. Vectorized in batches for large datasets.

    Args:
        baseline_scores: Per-sample scores from baseline run.
        candidate_scores: Per-sample scores from candidate run.
        significance: Significance level (default 0.05 for 95% CI).
        n_resamples: Number of bootstrap resamples.
        seed: Random seed for reproducibility.

    Returns:
        SignificanceResult with CI bounds and p-value.
    """
    if len(baseline_scores) != len(candidate_scores):
        raise ValueError(
            f"Score lists must have equal length: "
            f"{len(baseline_scores)} vs {len(candidate_scores)}"
        )

    if len(baseline_scores) == 0:
        return SignificanceResult(
            significant=False,
            p_value=1.0,
            ci_lower=0.0,
            ci_upper=0.0,
            method="bootstrap",
        )

    rng = np.random.default_rng(seed)
    diffs = np.array(candidate_scores) - np.array(baseline_scores)
    n = len(diffs)
    observed_mean = float(np.mean(diffs))

    # Vectorized bootstrap in batches to control memory
    boot_means = np.empty(n_resamples)
    for batch_start in range(0, n_resamples, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE, n_resamples)
        batch_count = batch_end - batch_start
        indices = rng.integers(0, n, size=(batch_count, n))
        boot_means[batch_start:batch_end] = np.mean(diffs[indices], axis=1)

    alpha = significance / 2
    ci_lower = float(np.percentile(boot_means, 100 * alpha))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha)))

    # Shifted bootstrap p-value (centered under H0)
    centered_diffs = diffs - observed_mean
    null_means = np.empty(n_resamples)
    for batch_start in range(0, n_resamples, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE, n_resamples)
        batch_count = batch_end - batch_start
        indices = rng.integers(0, n, size=(batch_count, n))
        null_means[batch_start:batch_end] = np.mean(centered_diffs[indices], axis=1)

    p_value = float(np.mean(np.abs(null_means) >= abs(observed_mean)))
    p_value = max(p_value, 1.0 / n_resamples)

    return SignificanceResult(
        significant=p_value < significance,
        p_value=p_value,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        method="bootstrap",
    )


def mcnemars_test(
    baseline_correct: list[bool],
    candidate_correct: list[bool],
    significance: float = 0.05,
) -> SignificanceResult:
    """McNemar's test for paired binary outcomes.

    Tests whether the rate of discordant pairs (one correct, one incorrect)
    differs significantly between runs. Uses the chi-square approximation
    with continuity correction.

    Args:
        baseline_correct: Per-sample correctness from baseline (True/False).
        candidate_correct: Per-sample correctness from candidate (True/False).
        significance: Significance level.

    Returns:
        SignificanceResult with p-value.
    """
    if len(baseline_correct) != len(candidate_correct):
        raise ValueError(
            f"Lists must have equal length: "
            f"{len(baseline_correct)} vs {len(candidate_correct)}"
        )

    if len(baseline_correct) == 0:
        return SignificanceResult(
            significant=False,
            p_value=1.0,
            ci_lower=0.0,
            ci_upper=0.0,
            method="mcnemar",
        )

    # b = baseline correct, candidate incorrect
    # c = baseline incorrect, candidate correct
    b = sum(1 for bl, cd in zip(baseline_correct, candidate_correct) if bl and not cd)
    c = sum(1 for bl, cd in zip(baseline_correct, candidate_correct) if not bl and cd)

    discordant = b + c
    if discordant == 0:
        return SignificanceResult(
            significant=False,
            p_value=1.0,
            ci_lower=0.0,
            ci_upper=0.0,
            method="mcnemar",
        )

    # Chi-square with continuity correction
    chi2 = (abs(b - c) - 1) ** 2 / discordant
    p_value = _chi2_sf(chi2, df=1)

    # CI on the difference in proportions
    n = len(baseline_correct)
    diff = (c - b) / n
    se = np.sqrt((b + c - (b - c) ** 2 / n) / n**2) if n > 0 else 0.0
    z = _normal_ppf(1 - significance / 2)
    ci_lower = float(diff - z * se)
    ci_upper = float(diff + z * se)

    return SignificanceResult(
        significant=p_value < significance,
        p_value=p_value,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        method="mcnemar",
    )


def permutation_test(
    baseline_scores: list[float],
    candidate_scores: list[float],
    significance: float = 0.05,
    n_iterations: int = _PERMUTATION_ITERATIONS,
    seed: int | None = 42,
) -> SignificanceResult:
    """Two-sided permutation test for paired samples.

    Randomly swaps baseline/candidate labels and computes the mean
    difference under the null hypothesis of no difference. Vectorized
    in batches for large datasets.

    Args:
        baseline_scores: Per-sample scores from baseline.
        candidate_scores: Per-sample scores from candidate.
        significance: Significance level.
        n_iterations: Number of permutation iterations.
        seed: Random seed for reproducibility.

    Returns:
        SignificanceResult with p-value.
    """
    if len(baseline_scores) != len(candidate_scores):
        raise ValueError(
            f"Score lists must have equal length: "
            f"{len(baseline_scores)} vs {len(candidate_scores)}"
        )

    if len(baseline_scores) == 0:
        return SignificanceResult(
            significant=False,
            p_value=1.0,
            ci_lower=0.0,
            ci_upper=0.0,
            method="permutation",
        )

    rng = np.random.default_rng(seed)
    bl = np.array(baseline_scores)
    cd = np.array(candidate_scores)
    diffs = cd - bl
    observed_diff = float(np.mean(diffs))
    n = len(bl)

    # Vectorized permutation test in batches
    count_extreme = 0
    for batch_start in range(0, n_iterations, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE, n_iterations)
        batch_count = batch_end - batch_start
        swaps = rng.random((batch_count, n)) < 0.5
        signed_diffs = np.where(swaps, -diffs, diffs)
        perm_means = np.mean(signed_diffs, axis=1)
        count_extreme += int(np.sum(np.abs(perm_means) >= abs(observed_diff)))

    p_value = (count_extreme + 1) / (n_iterations + 1)

    # Bootstrap CI for the difference
    boot_means = np.empty(n_iterations)
    for batch_start in range(0, n_iterations, _BATCH_SIZE):
        batch_end = min(batch_start + _BATCH_SIZE, n_iterations)
        batch_count = batch_end - batch_start
        indices = rng.integers(0, n, size=(batch_count, n))
        boot_means[batch_start:batch_end] = np.mean(diffs[indices], axis=1)

    alpha = significance / 2
    ci_lower = float(np.percentile(boot_means, 100 * alpha))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha)))

    return SignificanceResult(
        significant=p_value < significance,
        p_value=p_value,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        method="permutation",
    )


def cohens_d(
    baseline_scores: list[float], candidate_scores: list[float]
) -> float | None:
    """Compute Cohen's d effect size for paired samples.

    Measures the practical significance of the difference between two
    sets of scores, independent of sample size. Values around 0.2 are
    small, 0.5 medium, and 0.8 large.

    Args:
        baseline_scores: Per-sample scores from baseline.
        candidate_scores: Per-sample scores from candidate.

    Returns:
        Cohen's d value, or None if fewer than 2 samples.
    """
    diffs = np.array(candidate_scores) - np.array(baseline_scores)
    if len(diffs) < 2:
        return None
    sd = float(np.std(diffs, ddof=1))
    if sd == 0:
        return 0.0
    return float(np.mean(diffs)) / sd


def _normal_ppf(p: float) -> float:
    """Inverse CDF of standard normal (Abramowitz and Stegun 26.2.23)."""
    if p <= 0 or p >= 1:
        return 0.0
    t = sqrt(-2.0 * _log(1.0 - p if p > 0.5 else p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    result = t - (c0 + c1 * t + c2 * t * t) / (1 + d1 * t + d2 * t * t + d3 * t * t * t)
    return result if p > 0.5 else -result


def _chi2_sf(x: float, df: int = 1) -> float:
    """Survival function for chi-square distribution (no scipy).

    Uses the regularized incomplete gamma function approximation
    for df=1 (which reduces to 1 - erf(sqrt(x/2))).
    """
    if x <= 0:
        return 1.0
    if df != 1:
        logger.warning("chi2_sf approximation only supports df=1, got df=%d", df)
        return 0.0

    # For df=1, chi2 SF = 2 * (1 - Phi(sqrt(x))) = erfc(sqrt(x/2))
    return erfc(sqrt(x / 2))
