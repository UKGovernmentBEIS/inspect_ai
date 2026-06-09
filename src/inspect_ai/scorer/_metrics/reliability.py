"""Eval-reliability toolkit: paired comparisons, multiplicity control, power.

Eval results are routinely compared without statistical rigor — a model is
declared "better" on a one-number delta, suites of tasks are scanned for the
biggest gap, and sample sizes are chosen by habit. These helpers put error bars
and error control around those comparisons. They build on the same Central Limit
Theorem / clustered standard errors as :func:`stderr` and :func:`ci`, reuse
those helpers rather than reimplementing them, and depend only on stdlib
``statistics.NormalDist`` plus the already-present numpy (no new dependency).

Four pieces:

* :func:`paired_delta` — when two models are run on the **same** samples, the
  comparison is *paired*. The right standard error is the SD of the per-sample
  *differences*, which absorbs the sample-to-sample difficulty that is common to
  both models; treating the two score vectors as independent throws that away
  and inflates the error bar. This is the correctness point most ad-hoc eval
  comparisons get wrong.
* :func:`holm_bonferroni` / :func:`benjamini_hochberg` — comparing across a
  suite of N tasks multiplies false positives; these control the family-wise
  error rate (Holm) and the false discovery rate (Benjamini-Hochberg).
* :func:`min_samples_for_delta` / :func:`power_for_samples` — how many samples
  are needed before a delta of a given size is trustworthy, and the power of a
  given n.
* :func:`variance_surface` — a metric exposing the variance components (sample
  variance, CLT and clustered standard error, and the clustering design effect)
  behind a score, i.e. the noise floor of the eval.

Normal approximation: like :func:`ci`, the intervals and p-values use the
large-sample normal approximation (``z`` from ``NormalDist``) justified by the
CLT for the means/mean-differences of eval scores. The *paired* structure — not
``t`` vs ``z`` — is the statistical point here, and ``z`` keeps this stdlib-only
and consistent with :func:`ci`.
"""

from dataclasses import dataclass
from logging import getLogger
from statistics import NormalDist
from typing import Literal, Sequence, cast

from .._metric import (
    Metric,
    SampleScore,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)

logger = getLogger(__name__)

Alternative = Literal["two-sided", "greater", "less"]


# CLT / clustered standard-error helpers. These mirror the private estimators
# behind ``stderr()`` and are inlined here (rather than imported from
# ``._metrics.std``) so this module is self-contained. The same two helpers also
# appear in the ``ci()`` metric PR (#4161); if that lands, these can be removed
# and imported from ``._metrics.std`` instead. The numbers are identical.
def _clt_stderr(values: list[float]) -> float:
    """Central Limit Theorem standard error of the mean of ``values``."""
    import numpy as np

    n = len(values)
    # standard deviation divides by n - ddof, so guard against n < 2
    if (n - 1) < 1:
        return 0.0
    sample_std = np.std(values, ddof=1)
    return cast(float, sample_std / np.sqrt(n))


def _clustered_stderr(
    scores: list[SampleScore], cluster: str, to_float: ValueToFloat
) -> float:
    """Clustered standard error of the mean.

    For details, see Appendix A of https://arxiv.org/pdf/2411.00640. The version
    here uses a finite cluster correction (unlike the paper).
    """
    import numpy as np

    cluster_list = []
    value_list = []
    for sample_score in scores:
        if (
            sample_score.sample_metadata is None
            or cluster not in sample_score.sample_metadata
        ):
            raise ValueError(
                f"Sample {sample_score.sample_id} has no cluster metadata. To compute clustered standard errors, each sample metadata must have a value for '{cluster}'"
            )
        cluster_list.append(sample_score.sample_metadata[cluster])
        value_list.append(to_float(sample_score.score.value))
    clusters = np.array(cluster_list)
    values = np.array(value_list)
    mean = float(np.mean(values))

    unique_clusters = np.unique(clusters)
    cluster_count = len(unique_clusters)

    # The finite-cluster correction divides by (cluster_count - 1), so mirror the
    # non-clustered path's n < 2 guard and return 0 rather than NaN/inf when there
    # is only a single cluster.
    if cluster_count < 2:
        return 0.0

    clustered_variance = 0.0
    for cluster_id in unique_clusters:
        cluster_data = values[clusters == cluster_id]
        # X' \Omega X = \sum_i \sum_j (s_{i,c} - mean) * (s_{j,c} - mean)
        clustered_variance += np.outer(cluster_data - mean, cluster_data - mean).sum()

    # Multiply by C / (C - 1) to unbias the variance estimate.
    standard_error = np.sqrt(
        clustered_variance * cluster_count / (cluster_count - 1)
    ) / len(scores)
    return cast(float, standard_error)


def _two_sided_p(z_stat: float) -> float:
    """Two-sided p-value for a standard-normal test statistic."""
    return 2.0 * NormalDist().cdf(-abs(z_stat))


def _p_value(z_stat: float, alternative: Alternative) -> float:
    """p-value for ``z_stat`` under the requested alternative hypothesis."""
    if alternative == "two-sided":
        return _two_sided_p(z_stat)
    elif alternative == "greater":
        return 1.0 - NormalDist().cdf(z_stat)
    elif alternative == "less":
        return NormalDist().cdf(z_stat)
    else:
        raise ValueError(
            f"Unknown alternative '{alternative}' "
            "(expected 'two-sided', 'greater', or 'less')"
        )


def paired_delta(
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    level: float = 0.95,
    alternative: Alternative = "two-sided",
) -> dict[str, float]:
    """Paired confidence interval and significance test for a per-sample score delta.

    When two models/runs are evaluated on the **same** samples, their scores are
    paired, not independent. This computes the mean per-sample difference
    ``delta = mean(a_i - b_i)`` together with its standard error, a two-sided
    `level` confidence interval, and a significance test against ``delta = 0`` —
    all from the *differences*, so the (typically large) sample-to-sample
    difficulty shared by both models cancels out instead of inflating the error
    bar. The two vectors must already be aligned by sample (see
    :func:`align_paired_scores`).

    Args:
       scores_a: Per-sample scores for model/run A.
       scores_b: Per-sample scores for model/run B, aligned element-wise with
          `scores_a` (same sample at each index).
       level: Confidence level for the (two-sided) interval, in the open interval
          (0, 1). Default `0.95`.
       alternative: Alternative hypothesis for `p_value`. `"two-sided"` (default)
          tests `delta != 0`; `"greater"` tests `delta > 0` (A beats B); `"less"`
          tests `delta < 0`. The confidence interval is always the two-sided
          `level` interval regardless of this setting.

    Returns:
       Mapping with `delta` (mean A − B), `stderr` (paired standard error),
       `lower`/`upper` (interval bounds), `p_value`, and `n` (number of pairs).
    """
    import numpy as np

    if not 0.0 < level < 1.0:
        raise ValueError(
            f"paired_delta `level` must be in the open interval (0, 1), got {level}"
        )
    if len(scores_a) != len(scores_b):
        raise ValueError(
            "paired_delta requires aligned, equal-length score vectors "
            f"(got {len(scores_a)} and {len(scores_b)}); align by sample id first"
        )

    diffs = np.asarray(scores_a, dtype=float) - np.asarray(scores_b, dtype=float)
    n = len(diffs)
    delta = float(np.mean(diffs)) if n > 0 else 0.0

    if n < 2:
        # The standard error (and thus the interval/test) is undefined for fewer
        # than two pairs; collapse to the point estimate.
        return {
            "delta": delta,
            "stderr": 0.0,
            "lower": delta,
            "upper": delta,
            "p_value": 1.0,
            "n": float(n),
        }

    se = float(np.std(diffs, ddof=1) / np.sqrt(n))
    tail = (1.0 - level) / 2.0
    z = NormalDist().inv_cdf(1.0 - tail)

    if se == 0.0:
        # All differences identical: zero observed noise. The interval is a point;
        # the test is degenerate (exactly zero delta is "not significant", any
        # non-zero constant delta is "infinitely significant").
        p_value = 1.0 if delta == 0.0 else 0.0
        return {
            "delta": delta,
            "stderr": 0.0,
            "lower": delta,
            "upper": delta,
            "p_value": p_value,
            "n": float(n),
        }

    z_stat = delta / se
    return {
        "delta": delta,
        "stderr": se,
        "lower": float(delta - z * se),
        "upper": float(delta + z * se),
        "p_value": _p_value(z_stat, alternative),
        "n": float(n),
    }


def align_paired_scores(
    scores_a: list[SampleScore],
    scores_b: list[SampleScore],
    to_float: ValueToFloat = value_to_float(),
) -> tuple[list[float], list[float]]:
    """Align two `SampleScore` lists by `sample_id` into paired float vectors.

    Returns `(values_a, values_b)` ordered by the sample ids common to both,
    suitable for passing straight to :func:`paired_delta`. Raises if either list
    has duplicate sample ids or if the two id sets are not identical (a paired
    comparison requires the same samples on both sides).

    Args:
       scores_a: Scores for model/run A.
       scores_b: Scores for model/run B.
       to_float: Mapping from `Value` to float (see :func:`value_to_float`).
    """

    def _index(scores: list[SampleScore], label: str) -> dict[object, float]:
        index: dict[object, float] = {}
        for s in scores:
            if s.sample_id is None:
                raise ValueError(
                    f"align_paired_scores requires sample_id on every score ({label})"
                )
            if s.sample_id in index:
                raise ValueError(
                    f"duplicate sample_id {s.sample_id!r} in {label}; "
                    "a paired comparison needs one score per sample"
                )
            index[s.sample_id] = to_float(s.score.value)
        return index

    index_a = _index(scores_a, "scores_a")
    index_b = _index(scores_b, "scores_b")
    if index_a.keys() != index_b.keys():
        only_a = sorted(map(str, index_a.keys() - index_b.keys()))
        only_b = sorted(map(str, index_b.keys() - index_a.keys()))
        raise ValueError(
            "paired comparison requires identical sample ids on both sides; "
            f"only in A: {only_a[:5]}, only in B: {only_b[:5]}"
        )

    ids = sorted(index_a.keys(), key=str)
    return [index_a[i] for i in ids], [index_b[i] for i in ids]


@dataclass(frozen=True)
class MultipleComparison:
    """Result of a multiple-comparison correction over a family of tests.

    All lists preserve the order of the input p-values.

    Attributes:
       pvalues: The original (unadjusted) p-values.
       adjusted: Adjusted p-values (Holm-adjusted, or Benjamini-Hochberg
          q-values), each in [0, 1] and comparable directly against `alpha`.
       rejected: Whether each null hypothesis is rejected at `alpha`.
       method: `"holm-bonferroni"` or `"benjamini-hochberg"`.
       alpha: The error-rate level the correction controls.
    """

    pvalues: list[float]
    adjusted: list[float]
    rejected: list[bool]
    method: str
    alpha: float

    @property
    def num_rejected(self) -> int:
        """Number of hypotheses rejected (discoveries)."""
        return sum(self.rejected)


def _check_pvalues(pvalues: Sequence[float], alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in the open interval (0, 1), got {alpha}")
    if any(not (0.0 <= p <= 1.0) for p in pvalues):
        raise ValueError("p-values must all be in [0, 1]")


def holm_bonferroni(
    pvalues: Sequence[float], alpha: float = 0.05
) -> MultipleComparison:
    """Holm-Bonferroni step-down correction (controls family-wise error rate).

    Sorts the `m` p-values ascending and compares the k-th smallest against
    `alpha / (m - k + 1)`, rejecting until the first failure (step-down). Adjusted
    p-values are the running maximum of `(m - k + 1) * p_(k)` (clamped to 1), so
    they are monotone and directly comparable to `alpha`. Uniformly more powerful
    than plain Bonferroni while controlling the same (family-wise) error rate.

    Args:
       pvalues: Unadjusted p-values, one per task/comparison.
       alpha: Family-wise error rate to control. Default `0.05`.

    Returns:
       A :class:`MultipleComparison` (order matches the input).
    """
    _check_pvalues(pvalues, alpha)
    m = len(pvalues)
    if m == 0:
        return MultipleComparison([], [], [], "holm-bonferroni", alpha)

    # ascending order, remembering original positions
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted_sorted: list[float] = []
    running = 0.0
    for rank, idx in enumerate(order):  # rank = 0..m-1
        adj = min((m - rank) * pvalues[idx], 1.0)
        running = max(running, adj)  # enforce monotonicity
        adjusted_sorted.append(running)

    adjusted = [0.0] * m
    rejected = [False] * m
    for rank, idx in enumerate(order):
        adjusted[idx] = adjusted_sorted[rank]
        rejected[idx] = adjusted_sorted[rank] <= alpha
    return MultipleComparison(
        list(pvalues), adjusted, rejected, "holm-bonferroni", alpha
    )


def benjamini_hochberg(
    pvalues: Sequence[float], alpha: float = 0.05
) -> MultipleComparison:
    """Benjamini-Hochberg step-up correction (controls false discovery rate).

    Sorts the `m` p-values ascending and finds the largest k with
    `p_(k) <= (k / m) * alpha`, rejecting all hypotheses up to that rank
    (step-up). Adjusted values are BH q-values — the running minimum (from the
    largest p-value down) of `(m / k) * p_(k)`, clamped to 1 and monotone. FDR
    control is less conservative than family-wise control, so it makes more
    discoveries when many tasks truly differ.

    Args:
       pvalues: Unadjusted p-values, one per task/comparison.
       alpha: False discovery rate to control. Default `0.05`.

    Returns:
       A :class:`MultipleComparison` (order matches the input).
    """
    _check_pvalues(pvalues, alpha)
    m = len(pvalues)
    if m == 0:
        return MultipleComparison([], [], [], "benjamini-hochberg", alpha)

    order = sorted(range(m), key=lambda i: pvalues[i])  # ascending
    # q-values: walk from the largest p-value down, taking the running minimum of
    # (m / rank) * p, which makes the adjusted values monotone non-decreasing in p.
    qvalues_sorted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):  # rank = m..1 (1-based)
        idx = order[rank - 1]
        q = min((m / rank) * pvalues[idx], 1.0)
        running = min(running, q)
        qvalues_sorted[rank - 1] = running

    # a hypothesis is rejected iff its q-value <= alpha (equivalent to the step-up rule)
    adjusted = [0.0] * m
    rejected = [False] * m
    for rank, idx in enumerate(order):
        adjusted[idx] = qvalues_sorted[rank]
        rejected[idx] = qvalues_sorted[rank] <= alpha
    return MultipleComparison(
        list(pvalues), adjusted, rejected, "benjamini-hochberg", alpha
    )


def min_samples_for_delta(
    delta: float,
    sd_diff: float,
    power: float = 0.8,
    alpha: float = 0.05,
    alternative: Alternative = "two-sided",
) -> int:
    """Minimum paired sample size to detect a delta of size `delta`.

    Uses the normal-approximation power formula for a one-sample/paired mean test:

        n = ceil( ( (z_a + z_b) * sd_diff / |delta| ) ** 2 )

    where `z_a` is the level quantile (`1 - alpha/2` two-sided, `1 - alpha`
    one-sided) and `z_b = Φ⁻¹(power)`. `sd_diff` is the standard deviation of the
    per-sample *differences* (the same quantity whose SD drives
    :func:`paired_delta`); estimate it from a pilot run.

    Args:
       delta: Target effect size to detect (mean per-sample difference). Nonzero.
       sd_diff: Standard deviation of the per-sample differences. Positive.
       power: Desired power (probability of detecting a true `delta`). Default
          `0.8`. In the open interval (0, 1).
       alpha: Significance level. Default `0.05`. In the open interval (0, 1).
       alternative: `"two-sided"` (default) or one-sided (`"greater"`/`"less"`).

    Returns:
       The smallest integer number of paired samples.
    """
    import numpy as np

    if delta == 0.0:
        raise ValueError("delta must be nonzero (cannot size for a zero effect)")
    if sd_diff <= 0.0:
        raise ValueError(f"sd_diff must be positive, got {sd_diff}")
    if not 0.0 < power < 1.0:
        raise ValueError(f"power must be in the open interval (0, 1), got {power}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in the open interval (0, 1), got {alpha}")

    z_a = NormalDist().inv_cdf(
        1.0 - (alpha / 2.0 if alternative == "two-sided" else alpha)
    )
    z_b = NormalDist().inv_cdf(power)
    n = ((z_a + z_b) * sd_diff / abs(delta)) ** 2
    return int(np.ceil(n))


def power_for_samples(
    n: int,
    delta: float,
    sd_diff: float,
    alpha: float = 0.05,
    alternative: Alternative = "two-sided",
) -> float:
    """Power to detect `delta` with `n` paired samples (normal approximation).

    The inverse of :func:`min_samples_for_delta`:

        power = Φ( |delta| * sqrt(n) / sd_diff − z_a )

    Args:
       n: Number of paired samples (>= 1).
       delta: Effect size to detect. Nonzero.
       sd_diff: Standard deviation of the per-sample differences. Positive.
       alpha: Significance level. Default `0.05`.
       alternative: `"two-sided"` (default) or one-sided.

    Returns:
       Power in [0, 1].
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if delta == 0.0:
        raise ValueError("delta must be nonzero")
    if sd_diff <= 0.0:
        raise ValueError(f"sd_diff must be positive, got {sd_diff}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in the open interval (0, 1), got {alpha}")

    z_a = NormalDist().inv_cdf(
        1.0 - (alpha / 2.0 if alternative == "two-sided" else alpha)
    )
    ncp = abs(delta) * (n**0.5) / sd_diff
    return NormalDist().cdf(ncp - z_a)


@metric
def variance_surface(
    to_float: ValueToFloat = value_to_float(), cluster: str | None = None
) -> Metric:
    """Expose the variance components (noise floor) behind a mean score.

    Reports, as a mapping, the building blocks the standard error is made of, so
    the noise floor of an eval is visible rather than implicit:

    * `variance` — sample variance of the per-sample scores.
    * `stderr` — Central Limit Theorem standard error of the mean (i.i.d.).
    * `stderr_clustered` — clustered standard error (only when `cluster` is set).
    * `design_effect` — `(stderr_clustered / stderr) ** 2` (only with `cluster`):
      how much within-cluster correlation inflates the variance of the mean
      (1.0 = no clustering effect; > 1 means effectively fewer independent
      samples).
    * `n` — number of samples.

    Reuses the same `_clt_stderr` / `_clustered_stderr` helpers as :func:`stderr`
    and :func:`ci`, so the numbers are consistent across metrics.

    Args:
       to_float: Mapping from `Value` to float (see :func:`value_to_float`).
       cluster: Sample-metadata key identifying a cluster, to additionally report
          the clustered standard error and design effect.

    Returns:
       variance_surface metric returning a mapping of variance components.
    """

    def metric(scores: list[SampleScore]) -> Value:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]
        n = len(values)
        variance = float(np.var(values, ddof=1)) if n > 1 else 0.0
        clt_se = float(_clt_stderr(values))
        surface: dict[str, float] = {
            "variance": variance,
            "stderr": clt_se,
            "n": float(n),
        }
        if cluster is not None:
            clustered_se = float(_clustered_stderr(scores, cluster, to_float))
            surface["stderr_clustered"] = clustered_se
            surface["design_effect"] = (
                float((clustered_se / clt_se) ** 2) if clt_se > 0 else 0.0
            )
        return cast(Value, surface)

    return metric
