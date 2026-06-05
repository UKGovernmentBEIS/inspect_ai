from logging import getLogger
from statistics import NormalDist
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

    # Convert to numpy arrays and get unique clusters
    unique_clusters = np.unique(clusters)
    cluster_count = len(unique_clusters)

    # The finite-cluster correction divides by (cluster_count - 1), so mirror the
    # non-clustered path's n < 2 guard and return 0 rather than NaN/inf when there
    # is only a single cluster.
    if cluster_count < 2:
        return 0.0

    # Compute clustered variance using NumPy operations
    clustered_variance = 0.0
    for cluster_id in unique_clusters:
        # get a data vector for this cluster
        cluster_data = values[clusters == cluster_id]
        # this computes X' \Omega X = \sum_i \sum_j (s_{i,c} - mean) * (s_{j,c} - mean)
        clustered_variance += np.outer(cluster_data - mean, cluster_data - mean).sum()

    # Multiply by C / (C - 1) to unbias the variance estimate
    standard_error = np.sqrt(
        clustered_variance * cluster_count / (cluster_count - 1)
    ) / len(scores)

    return cast(float, standard_error)


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
        std = np.std(
            [
                np.mean(np.random.choice(values, len(values), replace=True))
                for _ in range(num_samples)
            ]
        )
        return cast(float, std.item())

    return metric


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
        return _clustered_stderr(scores, cluster, to_float)

    def metric(scores: list[SampleScore]) -> float:
        values = [to_float(score.score.value) for score in scores]
        return _clt_stderr(values)

    if cluster is not None:
        return clustered_metric

    return metric


@metric
def ci(
    level: float = 0.95,
    method: Literal["normal", "bootstrap"] = "normal",
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
       method: Interval method. `"normal"` uses a normal approximation
          (`mean ± z * stderr`, where `z` is the standard-normal quantile for
          `level`); this is appropriate for means of finitely-variance scores by
          the Central Limit Theorem. `"bootstrap"` uses a percentile bootstrap of
          the mean, which is useful for small samples or skewed score
          distributions.
       num_samples: Number of bootstrap resamples (only used when
          `method="bootstrap"`).
       to_float: Function for mapping `Value` to float for computing metrics. The
          default `value_to_float()` maps CORRECT ("C") to 1.0, INCORRECT ("I") to
          0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0, casts numeric values to
          float directly, and prints a warning and returns 0 if the `Value` is a
          complex object (list or dict).
       cluster (str | None): The key from the Sample metadata corresponding to a
          cluster identifier for computing
          [clustered](https://en.wikipedia.org/wiki/Clustered_standard_errors)
          intervals. When set, `method="normal"` uses the clustered standard
          error and `method="bootstrap"` resamples whole clusters (cluster
          bootstrap), so the interval accounts for within-cluster correlation.

    Returns:
       ci metric returning a mapping `{"lower": ..., "upper": ...}`.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"ci `level` must be in the open interval (0, 1), got {level}")

    tail = (1.0 - level) / 2.0

    def metric(scores: list[SampleScore]) -> Value:
        import numpy as np

        values = [to_float(score.score.value) for score in scores]
        if len(values) < 2:
            # interval is undefined for < 2 observations; collapse to the point
            point = float(values[0]) if values else 0.0
            return {"lower": point, "upper": point}

        if method == "normal":
            mean = float(np.mean(values))
            z = NormalDist().inv_cdf(1.0 - tail)
            if cluster is not None:
                se = _clustered_stderr(scores, cluster, to_float)
            else:
                se = _clt_stderr(values)
            return {"lower": mean - z * se, "upper": mean + z * se}
        elif method == "bootstrap":
            boot_means = _bootstrap_means(
                scores, values, to_float, cluster, num_samples
            )
            lower = float(np.quantile(boot_means, tail))
            upper = float(np.quantile(boot_means, 1.0 - tail))
            return {"lower": lower, "upper": upper}
        else:
            raise ValueError(
                f"Unknown ci method '{method}' (expected 'normal' or 'bootstrap')"
            )

    return metric


def _bootstrap_means(
    scores: list[SampleScore],
    values: list[float],
    to_float: ValueToFloat,
    cluster: str | None,
    num_samples: int,
) -> list[float]:
    """Bootstrap distribution of the mean.

    Resamples individual scores i.i.d. when `cluster` is None, otherwise resamples
    whole clusters with replacement (cluster bootstrap) so within-cluster
    correlation is preserved.
    """
    import numpy as np

    if cluster is None:
        data = np.asarray(values, dtype=float)
        n = len(data)
        return [
            float(np.mean(np.random.choice(data, n, replace=True)))
            for _ in range(num_samples)
        ]

    # group values by cluster
    groups: dict[object, list[float]] = {}
    for sample_score in scores:
        if (
            sample_score.sample_metadata is None
            or cluster not in sample_score.sample_metadata
        ):
            raise ValueError(
                f"Sample {sample_score.sample_id} has no cluster metadata. To compute clustered intervals, each sample metadata must have a value for '{cluster}'"
            )
        key = sample_score.sample_metadata[cluster]
        groups.setdefault(key, []).append(to_float(sample_score.score.value))

    cluster_arrays = [np.asarray(v, dtype=float) for v in groups.values()]
    num_clusters = len(cluster_arrays)
    means: list[float] = []
    for _ in range(num_samples):
        picks = np.random.choice(num_clusters, num_clusters, replace=True)
        resampled = np.concatenate([cluster_arrays[i] for i in picks])
        means.append(float(np.mean(resampled)))
    return means


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
