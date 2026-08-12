import math
from logging import getLogger
from typing import Literal, cast

from .._metric import (
    Metric,
    MetricProtocol,
    SampleScore,
    Value,
    ValueToFloat,
    metric,
)

logger = getLogger(__name__)


@metric
def aggregate(
    key: str,
    agg: Metric,
    *,
    to_float: ValueToFloat | None = None,
    on_missing: Literal["error", "skip", "zero"] = "error",
) -> Metric:
    """Apply `agg` to a single key extracted from each dict-valued `Score.value`.

    Many scorers emit dict-valued scores (multiple numeric fields per sample).
    `aggregate` selects one field by `key` and feeds the resulting scalar
    `SampleScore`s into `agg`, so any standard metric (`mean`, `stderr`,
    `std`, `accuracy`, ...) can be applied per key.

    A missing key (either `key not in value` or `value[key] is None`) is
    routed through `on_missing`. This matches the convention used by
    `inspect_evals.utils.metrics.mean_of`, so a `mean_of` → `aggregate` swap
    preserves behaviour.

    `on_missing="skip"` reduces the number of samples seen by `agg`, which
    changes the result of any aggregator that depends on sample count
    (e.g. `stderr`, `mean`, `std`, `var`). Two evals run with the same
    scorer can therefore report different stderrs purely because the rate
    of missing keys differed, not because of any difference in the
    underlying variance. Prefer `"zero"` if you want a constant denominator.

    If every sample is filtered out by `on_missing="skip"`, the aggregator
    returns `NaN` rather than calling `agg([])` (which most built-in metrics
    would raise on). This matches the `Score.unscored()` / NaN sentinel used
    elsewhere in the framework.

    Args:
       key: Field to extract from each sample's dict-valued `Score.value`.
       agg: Metric to apply to the extracted values.
       to_float: Optional function for mapping the extracted `Value` to a
          float before it reaches `agg`. The default (`None`) passes the raw
          extracted value straight through, so `agg`'s own conversion applies
          (e.g. `accuracy()`'s `to_float`, or `mean()`'s `as_float()`). Set
          this only when `agg` cannot convert the value itself — e.g. to feed
          string grades ("C"/"I") into `mean()`, which expects numerics. When
          set, pass `value_to_float()` (or a customised variant) to get the
          standard CORRECT/INCORRECT/PARTIAL/NOANSWER mapping.
       on_missing: How to handle samples whose `score.value` does not contain
          `key`, or contains `key` with a `None` value:

          - `"error"` (default): raise `ValueError`.
          - `"skip"`: exclude the sample from `agg`. Returns `NaN` if every
            sample is skipped.
          - `"zero"`: include the sample with value `0.0`.

    A per-key `NaN` value (e.g. `{"key": NaN}`) is always treated as
    unscored and skipped, independent of `on_missing` (which governs
    *missing keys*, a distinct concept). This matches the framework's
    dict-metric expansion, which skips NaN-valued keys rather than feeding
    them into the inner metric.

    Returns:
       Metric that aggregates `agg` over the `key` field. `NaN` if every
       sample is skipped (by `on_missing="skip"` and/or NaN-skipping).

    Raises:
       ValueError: If `on_missing` is not one of "error", "skip", "zero";
          if a sample's `score.value` is not a dict; or if `key` is missing
          (or `None`) and `on_missing="error"`.
    """
    if on_missing not in ("error", "skip", "zero"):
        raise ValueError(
            f"aggregate() got invalid on_missing={on_missing!r}; "
            "expected 'error', 'skip', or 'zero'."
        )

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

            raw = value.get(key)

            # A per-key NaN is unscored: skip it regardless of on_missing,
            # matching the framework's dict-metric expansion (results.py),
            # which excludes NaN-valued keys from the inner metric rather
            # than letting them drag the aggregate to NaN. (`isinstance`
            # excludes a missing key, whose `raw` is None.)
            if isinstance(raw, float) and math.isnan(raw):
                continue

            # Treat both "key absent" and "key present but None" as missing,
            # matching inspect_evals.utils.metrics.mean_of.
            if key in value and raw is not None:
                # Pass the raw value through by default so `agg`'s own
                # converter applies; only pre-convert when an explicit
                # to_float was supplied.
                extracted_value: str | int | float | bool = (
                    to_float(raw) if to_float is not None else raw
                )
            elif on_missing == "error":
                reason = "missing" if key not in value else "None"
                raise ValueError(
                    f"Sample {sample_score.sample_id} score key '{key}' is "
                    f"{reason}. Pass on_missing='skip' or on_missing='zero' "
                    "to aggregate() to allow missing keys."
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

        # All samples filtered: return NaN rather than call agg([]) (which
        # most built-in metrics raise on). Mirrors Score.unscored()'s NaN
        # sentinel.
        if not extracted:
            return math.nan

        return agg_protocol(extracted)

    return aggregate_metric
