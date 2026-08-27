import math
from logging import getLogger
from typing import Literal, cast

from .._metric import (
    Metric,
    SampleScore,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)

logger = getLogger(__name__)


@metric
def bootstrap_stderr(
    num_samples: int = 1000, to_float: ValueToFloat = value_to_float()
) -> Metric:
    """Standard error of the mean using bootstrap.

    Args:
       num_samples: Number of bootstrap samples to take.
       to_float: Function for mapping
          Value to float for computing metrics. The default
          `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
          NOANSWER ("N") to 0, casts numeric values to
          float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).

    Returns:
       bootstrap_stderr metric
    """

    def metric(scores: list[SampleScore]) -> float:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]
        if not values:
            # No scores to resample; return 0 rather than nan (and avoid the
            # numpy empty-slice warnings from the resampling loop), mirroring
            # the insufficient-data guards in stderr()/std()/var().
            return 0.0
        std = np.std(
            [
                np.mean(np.random.choice(values, len(values), replace=True))
                for _ in range(num_samples)
            ]
        )
        return cast(float, std.item())

    return metric


def _cluster_partition(
    scores: list[SampleScore], cluster: str, to_float: ValueToFloat, metric_name: str
) -> list[list[float]]:
    """Validate cluster metadata and partition score values by cluster id.

    Single source of truth for cluster identity: every consumer (clustered
    standard error, t degrees of freedom, cluster bootstrap) must derive its
    cluster count from the same partition, so equality semantics cannot drift
    between them. A missing key, `None`, or float NaN cluster id raises
    (float NaN metadata means "missing", matching the dataset convention).
    """
    groups: dict[object, list[float]] = {}
    for sample_score in scores:
        metadata = sample_score.sample_metadata
        cluster_id = metadata.get(cluster) if metadata is not None else None
        if cluster_id is None or (
            isinstance(cluster_id, float) and math.isnan(cluster_id)
        ):
            raise ValueError(
                f"Sample {sample_score.sample_id} has no cluster metadata. To compute `{metric_name}` with clustering, each sample metadata must have a value for '{cluster}'"
            )
        groups.setdefault(cluster_id, []).append(to_float(sample_score.score.value))
    return list(groups.values())


def _clustered_stderr(partition: list[list[float]]) -> float:
    """Clustered standard error of the mean over a cluster partition.

    For details, see Appendix A of https://arxiv.org/pdf/2411.00640.
    The version here uses a finite cluster correction (unlike the paper)
    """
    import numpy as np

    cluster_count = len(partition)

    # The finite-cluster correction divides by (cluster_count - 1), so
    # mirror the non-clustered path's n < 2 guard and return 0 rather
    # than NaN/inf when there is only a single cluster.
    if cluster_count < 2:
        return 0.0

    cluster_arrays = [np.asarray(group, dtype=float) for group in partition]
    values = np.concatenate(cluster_arrays)
    mean = float(np.mean(values))

    # sum_i sum_j (s_i - mean)(s_j - mean) over a cluster is the square
    # of that cluster's deviation sum. Computing the identity directly
    # avoids materialising a k-by-k outer product for every cluster.
    clustered_variance = 0.0
    for cluster_data in cluster_arrays:
        clustered_variance += ((cluster_data - mean).sum()) ** 2

    # Multiply by C / (C - 1) to unbias the variance estimate
    standard_error = np.sqrt(
        clustered_variance * cluster_count / (cluster_count - 1)
    ) / len(values)

    return cast(float, standard_error)


@metric
def stderr(
    to_float: ValueToFloat = value_to_float(), cluster: str | None = None
) -> Metric:
    """Standard error of the mean using Central Limit Theorem.

    Args:
       to_float: Function for mapping `Value` to float for computing
          metrics. The default `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0,
          casts numeric values to float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).
       cluster (str | None): The key from the Sample metadata
          corresponding to a cluster identifier for computing
          [clustered standard errors](https://en.wikipedia.org/wiki/Clustered_standard_errors).

    Returns:
       stderr metric
    """

    def clustered_metric(scores: list[SampleScore]) -> float:
        assert cluster is not None
        return _clustered_stderr(
            _cluster_partition(scores, cluster, to_float, "stderr")
        )

    def metric(scores: list[SampleScore]) -> float:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]
        n = len(values)

        # standard deviation is calculated by dividing by n-ddof so ensure
        # that we won't divide by zero
        if (n - 1) < 1:
            return 0

        # Calculate the sample standard deviation
        sample_std = np.std(values, ddof=1)

        # Calculate the standard error of the mean
        standard_error = sample_std / np.sqrt(n)

        return cast(float, standard_error)

    if cluster is not None:
        return clustered_metric

    return metric


@metric
def ci(
    level: float = 0.95,
    method: Literal["t", "bootstrap"] = "t",
    num_samples: int = 1000,
    to_float: ValueToFloat = value_to_float(),
    cluster: str | None = None,
) -> Metric:
    """Confidence interval for the mean of a list of scores.

    Reports the two-sided `level` confidence interval for the mean score as a
    mapping with `lower` and `upper` bounds. This complements `stderr()` (which
    reports only the standard error) by giving directly comparable interval
    bounds — e.g. for deciding whether two models' accuracies overlap.

    Args:
       level: Confidence level for the interval (e.g. `0.95` for a 95%
          interval). Must be in the open interval (0, 1).
       method: Interval method. `"t"` (the default) computes
          `mean ± t · stderr` where `t` is the Student-t critical value with
          `n - 1` degrees of freedom (`clusters - 1` for clustered intervals);
          this converges to the normal-approximation interval for large
          samples while remaining honest for small ones. `"bootstrap"` uses a
          percentile bootstrap of the mean, which is useful for skewed score
          distributions.
       num_samples: Number of bootstrap resamples (only used when
          `method="bootstrap"`).
       to_float: Function for mapping `Value` to float for computing metrics. The
          default `value_to_float()` maps CORRECT ("C") to 1.0, INCORRECT ("I") to
          0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0, casts numeric values to
          float directly, and prints a warning and returns 0 if the `Value` is a
          complex object (list or dict).
       cluster (str | None): The key from the Sample metadata corresponding to
          a cluster identifier for computing
          [clustered](https://en.wikipedia.org/wiki/Clustered_standard_errors)
          intervals. When set, `method="t"` uses the clustered standard error
          with `clusters - 1` degrees of freedom and `method="bootstrap"`
          resamples whole clusters (cluster bootstrap), so the interval
          accounts for within-cluster correlation.

    Returns:
       ci metric returning a mapping `{"lower": ..., "upper": ...}`.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"ci `level` must be in the open interval (0, 1), got {level}")
    if method not in ("t", "bootstrap"):
        raise ValueError(f"Unknown ci method '{method}' (expected 't' or 'bootstrap')")

    tail = (1.0 - level) / 2.0

    def metric_fn(scores: list[SampleScore]) -> Value:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]

        # validate and partition clusters before any short-circuit, so a
        # misconfigured cluster key fails loudly even on singleton inputs
        # (mirroring stderr's behavior); the partition is the single source
        # of truth for cluster identity across the SE, the degrees of
        # freedom, and the cluster bootstrap.
        partition = (
            _cluster_partition(scores, cluster, to_float, "ci")
            if cluster is not None
            else None
        )

        if len(values) < 2:
            # interval is undefined for < 2 observations; collapse to the point
            point = float(values[0]) if values else 0.0
            return {"lower": point, "upper": point}

        if method == "t":
            mean = float(np.mean(values))
            if partition is not None:
                se = _clustered_stderr(partition)
                df = max(len(partition) - 1, 1)
            else:
                se = _clt_stderr(values)
                df = len(values) - 1
            t = _t_inv_cdf(1.0 - tail, df)
            return {"lower": mean - t * se, "upper": mean + t * se}
        else:
            boot_means = _bootstrap_means(values, partition, num_samples)
            lower = float(np.quantile(boot_means, tail))
            upper = float(np.quantile(boot_means, 1.0 - tail))
            return {"lower": lower, "upper": upper}

    return metric_fn


def _clt_stderr(values: list[float]) -> float:
    """Central Limit Theorem standard error of the mean of `values`."""
    import numpy as np

    n = len(values)
    # standard deviation divides by n - ddof, so guard against n < 2
    if (n - 1) < 1:
        return 0.0
    sample_std = np.std(values, ddof=1)
    return cast(float, sample_std / np.sqrt(n))


def _bootstrap_means(
    values: list[float],
    partition: list[list[float]] | None,
    num_samples: int,
) -> list[float]:
    """Bootstrap distribution of the mean.

    Resamples individual scores i.i.d. when `partition` is None, otherwise
    resamples whole clusters with replacement (cluster bootstrap) so
    within-cluster correlation is preserved.
    """
    import numpy as np

    if partition is None:
        data = np.asarray(values, dtype=float)
        n = len(data)
        return [
            float(np.mean(np.random.choice(data, n, replace=True)))
            for _ in range(num_samples)
        ]

    cluster_arrays = [np.asarray(group, dtype=float) for group in partition]
    num_clusters = len(cluster_arrays)
    means: list[float] = []
    for _ in range(num_samples):
        picks = np.random.choice(num_clusters, num_clusters, replace=True)
        resampled = np.concatenate([cluster_arrays[i] for i in picks])
        means.append(float(np.mean(resampled)))
    return means


def _t_inv_cdf(p: float, df: int) -> float:
    """Student-t inverse CDF, dependency-free.

    Exact to bisection precision via the regularized incomplete beta
    function (for t >= 0, `F(t) = 1 - I_x(df/2, 1/2) / 2` with
    `x = df / (df + t^2)`), rather than a Cornish-Fisher-style series —
    the series is least accurate at exactly the small `df` this exists
    to serve. Called once per metric evaluation, so speed is irrelevant.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"t quantile requires 0 < p < 1, got {p}")
    if df < 1:
        raise ValueError(f"t quantile requires df >= 1, got {df}")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -_t_inv_cdf(1.0 - p, df)

    def cdf(t: float) -> float:
        x = df / (df + t * t)
        return 1.0 - 0.5 * _reg_inc_beta(df / 2.0, 0.5, x)

    # bracket the quantile, then bisect
    hi = 1.0
    while cdf(hi) < p:
        hi *= 2.0
    lo = 0.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _reg_inc_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) (Numerical Recipes 6.4)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln_front)
    # continued fraction converges fast for x < (a + 1) / (a + b + 2);
    # otherwise use the symmetry I_x(a, b) = 1 - I_(1-x)(b, a)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    else:
        return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz's continued fraction for the incomplete beta function."""
    max_iterations = 200
    epsilon = 3e-16
    tiny = 1e-300

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iterations + 1):
        m2 = 2 * m
        # even step
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        # odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < epsilon:
            break
    return h


@metric
def std(to_float: ValueToFloat = value_to_float()) -> Metric:
    """Calculates the sample standard deviation of a list of scores.

    Args:
       to_float: Function for mapping `Value` to float for computing
          metrics. The default `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0,
          casts numeric values to float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).


    Returns:
        std metric
    """

    def metric(scores: list[SampleScore]) -> float:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]
        n = len(values)

        # standard deviation is calculated by dividing by n-ddof so ensure
        # that we won't divide by zero
        if (n - 1) < 1:
            return 0

        # Calculate the sample standard deviation
        sample_std = np.std(values, ddof=1)

        return cast(float, sample_std)

    return metric


@metric
def var(to_float: ValueToFloat = value_to_float()) -> Metric:
    """Compute the sample variance of a list of scores.

    Args:
        to_float (ValueToFloat): Function for mapping
            Value to float for computing metrics. The default
            `value_to_float()` maps CORRECT ("C") to 1.0,
            INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
            NOANSWER ("N") to 0, casts numeric values to
            float directly, and prints a warning and returns
            0 if the Value is a complex object (list or dict).

    Returns:
       var metric
    """

    def metric(scores: list[SampleScore]) -> float:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]
        n = len(values)
        # variance is calculated by dividing by n-ddof so ensure
        # that we won't divide by zero
        if (n - 1) < 1:
            return 0

        variance = np.var(values, ddof=1)

        return cast(float, variance)

    return metric
