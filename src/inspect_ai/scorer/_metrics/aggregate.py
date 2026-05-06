from logging import getLogger
from typing import Literal, cast

from .._metric import (
    Metric,
    MetricProtocol,
    SampleScore,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)

logger = getLogger(__name__)


@metric
def aggregate(
    key: str,
    agg: Metric,
    *,
    to_float: ValueToFloat = value_to_float(),
    on_missing: Literal["error", "skip", "zero"] = "error",
) -> Metric:
    """Apply `agg` to a single key extracted from each dict-valued `Score.value`.

    Many scorers emit dict-valued scores (multiple numeric fields per sample).
    `aggregate` selects one field by `key` and feeds the resulting scalar
    `SampleScore`s into `agg`, so any standard metric (`mean`, `stderr`,
    `std`, `accuracy`, ...) can be applied per key.

    Args:
       key: Field to extract from each sample's dict-valued `Score.value`.
       agg: Metric to apply to the extracted values.
       to_float: Function for mapping the extracted `Value` to a float. The
          default `value_to_float()` maps CORRECT ("C") to 1.0, INCORRECT ("I")
          to 0, PARTIAL ("P") to 0.5, and NOANSWER ("N") to 0, casts numeric
          values to float directly, and prints a warning and returns 0 if the
          Value is a complex object (list or dict).
       on_missing: How to handle samples whose `score.value` does not contain
          `key`:

          - `"error"` (default): raise `ValueError`.
          - `"skip"`: exclude the sample from `agg`.
          - `"zero"`: include the sample with value `0.0`.

    Returns:
       Metric that aggregates `agg` over the `key` field.

    Raises:
       ValueError: If a sample's `score.value` is not a dict, or if `key` is
          missing from a sample's score and `on_missing="error"`.
    """

    def aggregate_metric(scores: list[SampleScore]) -> Value:
        agg_protocol = cast(MetricProtocol, agg)

        extracted: list[SampleScore] = []
        for sample_score in scores:
            value = sample_score.score.value
            if not isinstance(value, dict):
                raise ValueError(
                    f"Sample {sample_score.sample_id} has non-dict score value "
                    f"({type(value).__name__}); aggregate(key=...) requires "
                    "dict-valued Score.value."
                )

            if key in value:
                extracted_value: float = to_float(value[key])
            elif on_missing == "error":
                raise ValueError(
                    f"Sample {sample_score.sample_id} score is missing key "
                    f"'{key}'. Pass on_missing='skip' or on_missing='zero' to "
                    "aggregate() to allow missing keys."
                )
            elif on_missing == "skip":
                continue
            else:  # "zero"
                extracted_value = 0.0

            extracted.append(
                SampleScore(
                    score=sample_score.score.model_copy(
                        update={"value": extracted_value}
                    ),
                    sample_id=sample_score.sample_id,
                    sample_metadata=sample_score.sample_metadata,
                    scorer=sample_score.scorer,
                )
            )

        return agg_protocol(extracted)

    return aggregate_metric
