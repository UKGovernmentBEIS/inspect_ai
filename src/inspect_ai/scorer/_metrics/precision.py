from logging import getLogger

from .._metric import (
    Metric,
    SampleScore,
    ValueToFloat,
    metric,
    precision_value_to_float,
)

logger = getLogger(__name__)


@metric
def precision(to_float: ValueToFloat = precision_value_to_float()) -> Metric:
    r"""Compute proportion of total answers which are correct to total questions answered.

    Args:
       to_float: Function for mapping `Value` to float for computing
          metrics. The default `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to -1,
          casts numeric values to float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).

          Note that this value_to_float must return -1 for NOANSWER in order for
          the precision metric to be computed correctly.

    Returns:
       Precision metric
    """

    def metric(scores: list[SampleScore]) -> float:
        answered = [item for item in scores if to_float(item.score.value) != -1]

        total = 0.0
        for item in answered:
            total += to_float(item.score.value)
        return total / float(len(answered))

    return metric


@metric
def coverage(to_float: ValueToFloat = precision_value_to_float()) -> Metric:
    r"""Compute proportion of answered questions to total questions.

    Args:
       to_float: Function for mapping `Value` to float for computing
          metrics. The default `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to -1,
          casts numeric values to float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).

          Note that this value_to_float must return -1 for NOANSWER in order for
          the precision metric to be computed correctly.

    Returns:
       Coverage metric
    """

    def metric(scores: list[SampleScore]) -> float:
        # Filter to only answered questions
        answered = [item for item in scores if to_float(item.score.value) != -1]
        return float(len(answered)) / float(len(scores))

    return metric
