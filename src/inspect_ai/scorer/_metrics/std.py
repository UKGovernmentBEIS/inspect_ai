from logging import getLogger
from typing import Optional, cast

import numpy as np
from numpy._typing import NDArray

from .._metric import (
    Metric,
    ReducedScore,
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
       num_samples (int): Number of bootstrap samples to take.
       to_float (ValueToFloat): Function for mapping
         Value to float for computing metrics. The default
         `value_to_float()` maps CORRECT ("C") to 1.0,
         INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
         NOANSWER ("N") to 0, casts numeric values to
         float directly, and prints a warning and returns
         0 if the Value is a complex object (list or dict).

    Returns:
       bootstrap_stderr metric
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


class InhomogenousClustersError(ValueError):
    pass


@metric
def stderr(
    num_samples: int = 1000, to_float: ValueToFloat = value_to_float()
) -> Metric:
    """Standard error of the mean using hierarchical bootstrap.

    This takes into account variation both accross ``ReducedScore``s (questions)
    and within each ``ReducedScore`` (accross epochs).

    The former corresponds to imprecision in our estimate due to the finite number of benchmark
    questions (which we can think of as drawn from a hypothetical super-population). The latter
    corresponds to imprecision in our estimate due to non-deterministic model output.

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
        stderr metric
    """

    def metric(scores: list[ReducedScore]) -> float:
        # Extract child scores
        fscores: list[list[float]] = []
        for score in scores:
            if not score.children:
                raise ValueError("Hierarchical bootstrap requires non-empty clusters")
            values = [to_float(child.value) for child in score.children]
            fscores.append(values)

        try:
            bootstrap_means = hierarchical_bootstrap(fscores, num_samples=num_samples)
        except InhomogenousClustersError:
            # Sometimes Inspect wants to score an eval while it's still running, so this function
            # will be called with clusters of different sizes. Handling this case is left for
            # future work. For now just make sure we don't raise.
            return float("nan")
        stderr = np.std(bootstrap_means)
        return cast(float, stderr)

    return metric


def hierarchical_bootstrap(
    scores: list[list[float]],
    num_samples: int = 1000,
    random_state: Optional[int] = None,
) -> NDArray[np.float64]:
    """Efficient implementation of hierarchical bootstrap using vectorized operations.

    See tests for a more readable counterpart using loops, ``readable_hierarchical_bootstrap``.

    Implements hierarchical bootstrap with two levels: resample clusters, then resample members
    within each cluster, both with replacement. In the most common use case (the ``stderr``
    metric), the clusters are benchmark questions, and the members are scores from different epochs.
    """
    rng = np.random.default_rng(random_state)

    try:
        scores_array = np.array(scores)  # Shape: (n_clusters, n_members)
    except ValueError:
        raise InhomogenousClustersError()
    n_clusters, n_members = scores_array.shape

    # Generate all random indices at once
    cluster_indices = rng.integers(
        0, n_clusters, size=(num_samples, n_clusters)
    )  # Shape: (num_samples, n_clusters)
    member_indices = rng.integers(
        0, n_members, size=(num_samples, n_clusters, n_members)
    )  # Shape: (num_samples, n_clusters, n_members)

    # Create index arrays
    c_idx = cluster_indices[:, :, None]  # Shape: (num_samples, n_clusters, 1)
    m_idx = member_indices  # Shape: (num_samples, n_clusters, n_members)

    # Resample all data points at once
    resampled_data = scores_array[
        c_idx, m_idx
    ]  # Shape: (num_samples, n_clusters, n_members)

    # Average over members first
    cluster_means = np.mean(resampled_data, axis=2)  # Shape: (num_samples, n_clusters)

    # Then average over clusters
    bootstrap_means = np.mean(cluster_means, axis=1)  # Shape: (num_samples,)

    return cast(NDArray[np.float64], bootstrap_means)


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
