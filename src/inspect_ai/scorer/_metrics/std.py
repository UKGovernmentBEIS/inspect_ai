from logging import getLogger
from typing import cast

import numpy as np

from .._metric import (
    Metric,
    SampleScore,
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
        """Computes a clustered standard error.

        For details, see Appendix A of https://arxiv.org/pdf/2411.00640.
        The version here uses a finite cluster correction (unlike the paper)
        """
        assert cluster is not None
        cluster_list = []
        value_list = []
        for sample_score in scores:
            if (
                sample_score.sample_metadata is None
                or cluster not in sample_score.sample_metadata
            ):
                raise ValueError(
                    f"Sample {sample_score.sample_id} has no cluster metadata. To compute `stderr` with clustering, each sample metadata must have a value for '{cluster}'"
                )
            cluster_list.append(sample_score.sample_metadata[cluster])
            value_list.append(to_float(sample_score.score.value))
        clusters = np.array(cluster_list)
        values = np.array(value_list)
        mean = float(np.mean(values))

        # Convert to numpy arrays and get unique clusters
        unique_clusters = np.unique(clusters)
        cluster_count = len(unique_clusters)

        # Compute clustered variance using NumPy operations
        clustered_variance = 0.0
        for cluster_id in unique_clusters:
            # get a data vector for this cluster
            cluster_data = values[clusters == cluster_id]
            # this computes X' \Omega X = \sum_i \sum_j (s_{i,c} - mean) * (s_{j,c} - mean)
            clustered_variance += np.outer(
                cluster_data - mean, cluster_data - mean
            ).sum()

        # Multiply by C / (C - 1) to unbias the variance estimate
        standard_error = np.sqrt(
            clustered_variance * cluster_count / (cluster_count - 1)
        ) / len(scores)

        return cast(float, standard_error)

    def metric(scores: list[SampleScore]) -> float:
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
        values = [to_float(score.score.value) for score in scores]
        n = len(values)
        # variance is calculated by dividing by n-ddof so ensure
        # that we won't divide by zero
        if (n - 1) < 1:
            return 0

        variance = np.var(values, ddof=1)

        return cast(float, variance)

    return metric
