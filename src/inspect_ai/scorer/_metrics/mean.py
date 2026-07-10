from .._metric import (
    Metric,
    SampleScore,
    ValueToFloat,
    metric,
    value_to_float,
)
from .._reducer.reducer import _is_unscored


@metric
def mean(to_float: ValueToFloat = value_to_float()) -> Metric:
    """Compute mean of all scored samples.

    Unscored samples, represented by a NaN root value such as
    ``Score.unscored()``, are excluded from the mean calculation.

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

        values = []
        for item in scores:
            if _is_unscored(item.score.value):
                continue
            values.append(to_float(item.score.value))
        if not values:
            return 0.0
        return np.mean(values).item()

    return metric
