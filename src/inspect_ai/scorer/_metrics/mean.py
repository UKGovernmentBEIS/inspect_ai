from .._metric import (
    Metric,
    SampleScore,
    ValueToFloat,
    metric,
    value_to_float,
)


@metric
def mean(to_float: ValueToFloat = value_to_float()) -> Metric:
    """Compute mean of all scores.

    Args:
       to_float: Function for mapping `Value` to float for computing
          metrics. The default `value_to_float()` maps CORRECT ("C") to 1.0,
          INCORRECT ("I") to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0,
          casts numeric values to float directly, and prints a warning and returns
          0 if the Value is a complex object (list or dict).

    Returns:
       mean metric
    """

    def metric(scores: list[SampleScore]) -> float:
        import numpy as np

        return np.mean([to_float(score.score.value) for score in scores]).item()

    return metric
