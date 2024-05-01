from logging import getLogger

from .._metric import (
    Metric,
    Score,
    ValueToFloat,
    metric,
    value_to_float,
)

logger = getLogger(__name__)


@metric
def accuracy(to_float: ValueToFloat = value_to_float()) -> Metric:
    r"""Compute proportion of total answers which are correct.

    Args:
      to_float (ValueToFloat): Function for mapping
        Value to float for computing metrics. The default
        `value_to_float()` maps CORRECT ("C") to 1.0,
        INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and
        NOANSWER ("N") to 0, casts numeric values to
        float directly, and prints a warning and returns
        0 if the Value is a complex object (list or dict).

    Returns:
       Accuracy metric
    """

    def metric(scores: list[Score]) -> float:
        total = 0.0
        for item in scores:
            total += to_float(item.value)
        return total / float(len(scores))

    return metric
