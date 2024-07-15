from logging import getLogger
from typing import cast

import numpy as np

from .._metric import (
    Metric,
    Score,
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

    def metric(scores: list[Score]) -> float:
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
    """Standard error of the mean using Central Limit Theorem.

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

    def metric(scores: list[Score]) -> float:
        values = [to_float(score.value) for score in scores]
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

    def metric(scores: list[Score]) -> float:
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
