from logging import getLogger
from typing import cast

import numpy as np

from .._metric import (
    Metric,
    ReducedScore,
    ValueToFloat,
    metric,
    value_to_float,
)

logger = getLogger(__name__)


@metric
def bootstrap_std(
    num_samples: int = 1000, to_float: ValueToFloat = value_to_float()
) -> Metric:
    """Standard deviation of a bootstrapped estimate of the mean.

    Args:
       num_samples (int): Number of bootstrap samples to take.
       to_float (ValueToFloat): Function for mapping
         Value to float for computing metrics. The default
         `value_to_float()` maps CORRECT ("C") to 1.0,
         INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
         NOANSWER ("N") to 0, casts numeric values to
         float directly, and prints a warning and returns
         0 if the Value is a complex object (list or dict).

    Returns:
       bootstrap_std metric
    """

    def metric(scores: list[ReducedScore]) -> float:
        values = [to_float(score.value) for score in scores]
        std = np.std(
            [
                np.mean(np.random.choice(values, len(values), replace=True))
                for _ in range(num_samples)
            ]
        )
        return cast(float, std.item())

    return metric


@metric
def stderr(to_float: ValueToFloat = value_to_float()) -> Metric:
    """Clustered standard error of the mean.

    Where each ``ReducedScore``'s children form a cluster.
    If ``epochs=1`` such that each ``ReducedScore`` has only one child, clustered standard errors
    reduce to heteroskedasticity-robust (White) standard errors.

    See also Miller, 'Adding Error Bars to Evals': https://arxiv.org/abs/2411.00640

    Args:
        to_float (ValueToFloat): Function for mapping
            Value to float for computing metrics. The default
            `value_to_float()` maps CORRECT ("C") to 1.0,
            INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
            NOANSWER ("N") to 0, casts numeric values to
            float directly, and prints a warning and returns
            0 if the Value is a complex object (list or dict).

    Returns:
        stderr metric
    """

    def metric(scores: list[ReducedScore]) -> float:
        # Extract child scores
        fscores: list[list[float]] = []
        for score in scores:
            if not score.children:
                raise ValueError("Clustered standard error requires non-empty clusters")
            values = [to_float(child.value) for child in score.children]
            fscores.append(values)

        n = sum(len(cluster) for cluster in fscores)  # total number of scores
        g = len(scores)  # number of clusters

        # Ensure that we won't divide by zero if there is only one cluster
        if (g - 1) == 0:
            return 0.0

        overall_mean = sum(sum(cluster) for cluster in fscores) / n

        # Calculate unclustered variance term
        unclustered_var = sum(
            sum((x - overall_mean) ** 2 for x in cluster) for cluster in fscores
        ) / (n**2)

        # Calculate between-observation covariance terms within clusters
        cluster_covar = 0.0
        for cluster in fscores:
            # Sum of (x_i - mean)(x_j - mean) for all i != j in cluster
            cluster_size = len(cluster)
            if cluster_size > 1:
                cluster_dev = [x - overall_mean for x in cluster]
                cluster_covar += sum(
                    cluster_dev[i] * cluster_dev[j]
                    for i in range(cluster_size)
                    for j in range(cluster_size)
                    if i != j
                )

        # Add covariance term to unclustered variance
        clustered_var = unclustered_var + (cluster_covar / (n**2))

        # Apply small sample correction g/(g-1) to variance
        clustered_var *= g / (g - 1)

        # Return standard error
        stderr = np.sqrt(clustered_var)
        return cast(float, stderr)

    return metric


@metric
def std(to_float: ValueToFloat = value_to_float()) -> Metric:
    """Calculates the sample standard deviation of a list of scores.

    Args:
        to_float (ValueToFloat): Function for mapping
            Value to float for computing metrics. The default
            `value_to_float()` maps CORRECT ("C") to 1.0,
            INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
            NOANSWER ("N") to 0, casts numeric values to
            float directly, and prints a warning and returns
            0 if the Value is a complex object (list or dict).

    Returns:
        std metric
    """

    def metric(scores: list[ReducedScore]) -> float:
        values = [to_float(score.value) for score in scores]
        n = len(values)

        # standard deviation is calculated by dividing by n-ddof so ensure
        # that we won't divide by zero
        if (n - 1) < 1:
            return 0

        # Calculate the sample standard deviation
        sample_std = np.std(values, ddof=1)

        return cast(float, sample_std)

    return metric
