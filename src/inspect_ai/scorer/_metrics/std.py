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
