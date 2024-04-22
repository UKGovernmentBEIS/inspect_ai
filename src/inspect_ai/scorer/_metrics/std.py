from logging import getLogger
from typing import cast

import numpy as np

from .._metric import CORRECT, INCORRECT, PARTIAL, Metric, Score, Value, metric

logger = getLogger(__name__)


@metric
def bootstrap_std(
    num_samples: int = 1000,
    correct: Value = CORRECT,
    incorrect: Value = INCORRECT,
    partial: Value | None = PARTIAL,
) -> Metric:
    """Standard deviation of a bootstrapped estimate of the mean.

    Args:
       num_samples (int): Number of bootstrap samples to take.
       correct (Value): Value to compare against.
       incorrect (Value): Value that represents an incorrect answer.
       partial (Value): Value to assign partial credit for.

    Returns:
       bootstrap_std metric
    """

    def as_float(score: Score) -> float:
        if isinstance(score.value, (int, float, bool)):
            return float(score.value)
        elif score.value == correct:
            return 1.0
        elif score.value == partial:
            return 0.5
        elif score.value == incorrect:
            return 0
        else:
            logger.warning(
                "Unexpected item value for bootstrap_std metric: {item.value}"
            )
            return 0

    def metric(scores: list[Score]) -> float:
        values = [as_float(score) for score in scores]
        std = np.std(
            [
                np.mean(np.random.choice(values, len(values), replace=True))
                for _ in range(num_samples)
            ]
        )
        return cast(float, std.item())

    return metric
