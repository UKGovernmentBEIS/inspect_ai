from logging import getLogger

from .._metric import (
    Metric,
    SampleScore,
    ValueToFloat,
    metric,
    value_to_float,
)
from .._reducer.reducer import _is_unscored

logger = getLogger(__name__)


@metric
def accuracy(to_float: ValueToFloat = value_to_float()) -> Metric:
    r"""Compute proportion of scored answers which are correct.

    Unscored samples, represented by a NaN root value such as
    ``Score.unscored()``, are excluded from both numerator and denominator.

    Args:
       to_float: Function for mapping `Value` to float for computing
          metrics. The default `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0,
          casts numeric values to float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).

    Returns:
       Accuracy metric
    """

    def metric(scores: list[SampleScore]) -> float:
        if not scores:
            return 0.0
        total = 0.0
        scored = 0
        for item in scores:
            if _is_unscored(item.score.value):
                continue
            total += to_float(item.score.value)
            scored += 1
        if scored == 0:
            return 0.0
        return total / float(scored)

    return metric
