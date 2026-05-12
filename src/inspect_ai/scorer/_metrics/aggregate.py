from typing import Literal, cast

from .._metric import (
    Metric,
    MetricProtocol,
    SampleScore,
    Score,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)


@metric
def aggregate(
    key: str,
    agg: Metric,
    *,
    to_float: ValueToFloat = value_to_float(),
    on_missing: Literal["error", "skip", "zero"] = "error",
) -> Metric:
    """Apply ``agg`` to the ``key`` field extracted from each dict-valued ``Score.value``.

    Many scorers emit a ``dict`` as ``Score.value`` (multiple numeric fields
    per sample). ``aggregate`` composes any existing ``Metric`` (``mean``,
    ``stderr``, ``std``, etc.) with a key-selector so per-key aggregation
    doesn't have to be re-implemented in every eval.

    Args:
        key: The key to extract from each sample's ``score.value`` dict.
        agg: The aggregator metric to apply once the per-sample scalar values
            have been unwrapped. Typically ``mean()``, ``stderr()``, ``std()``,
            ``accuracy()``, or any other registered ``Metric`` whose
            implementation reads ``score.value``.
        to_float: Function for mapping the extracted dict-value to ``float``.
            Defaults to :func:`value_to_float` (handles CORRECT/INCORRECT,
            booleans, and numeric values).
        on_missing: How to handle samples whose ``score.value`` dict is
            missing ``key`` or has it set to ``None``:

            - ``"error"`` (default) -- raise ``ValueError``.
            - ``"skip"`` -- exclude the sample from the aggregator.
            - ``"zero"`` -- treat the missing entry as ``0.0``.

    Returns:
        A new metric that returns whatever ``agg`` returns when applied to the
        per-sample scalar values extracted at ``key``.

    Raises:
        ValueError: If ``Score.value`` is not a ``dict``, or if ``key`` is
            missing/``None`` and ``on_missing="error"``.

    Examples:
        ```python
        from inspect_ai.scorer import (
            Metric, aggregate, mean, metric, stderr,
        )

        @metric
        def element_accuracy() -> Metric:
            return aggregate("element_acc", agg=mean(), on_missing="skip")

        @metric
        def element_accuracy_stderr() -> Metric:
            return aggregate("element_acc", agg=stderr(), on_missing="skip")
        ```
    """
    agg_protocol = cast(MetricProtocol, agg)

    def aggregate_metric(scores: list[SampleScore]) -> Value:
        unwrapped: list[SampleScore] = []
        for sample_score in scores:
            value = sample_score.score.value
            if not isinstance(value, dict):
                raise ValueError(
                    f"aggregate('{key}') requires Score.value to be a dict, "
                    f"got {type(value).__name__}: {value!r}"
                )

            if key not in value or value[key] is None:
                if on_missing == "error":
                    if key not in value:
                        raise ValueError(
                            f"aggregate('{key}') key not found in Score.value. "
                            f"Available keys: {list(value.keys())}"
                        )
                    raise ValueError(
                        f"aggregate('{key}') value is None in Score.value."
                    )
                if on_missing == "skip":
                    continue
                # on_missing == "zero"
                extracted: float = 0.0
            else:
                extracted = to_float(value[key])

            # Rebuild the SampleScore with the unwrapped scalar value so that
            # ``agg`` (which reads ``score.value`` via ``score.as_float()`` or
            # ``to_float``) sees a single number rather than the original dict.
            unwrapped.append(
                SampleScore(
                    score=Score(
                        value=extracted,
                        answer=sample_score.score.answer,
                        explanation=sample_score.score.explanation,
                        metadata=sample_score.score.metadata,
                        history=sample_score.score.history,
                    ),
                    sample_id=sample_score.sample_id,
                    sample_metadata=sample_score.sample_metadata,
                    scorer=sample_score.scorer,
                )
            )

        return agg_protocol(unwrapped)

    return aggregate_metric
