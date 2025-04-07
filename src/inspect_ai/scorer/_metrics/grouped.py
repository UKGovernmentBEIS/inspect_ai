from typing import Literal, cast

import numpy as np

from inspect_ai.scorer._metric import (
    Metric,
    MetricProtocol,
    SampleScore,
    Value,
    ValueToFloat,
    metric,
    value_to_float,
)


@metric
def grouped(
    metric: Metric,
    group_key: str,
    *,
    all: Literal["samples", "groups"] | Literal[False] = "samples",
    all_label: str = "all",
    value_to_float: ValueToFloat = value_to_float(),
) -> Metric:
    """
    Creates a grouped metric that applies the given metric to subgroups of samples.

    Args:
      metric: The metric to apply to each group of samples.
      group_key: The metadata key used to group samples. Each sample must have this key in its metadata.
      all: How to compute the "all" aggregate score:
          - "samples": Apply the metric to all samples regardless of groups
          - "groups": Calculate the mean of all group scores
          - False: Don't calculate an aggregate score
      all_label: The label for the "all" key in the returned dictionary.
      value_to_float: Function to convert metric values to floats, used when all="groups".

    Returns:
        A new metric function that returns a dictionary mapping group names to their scores,
        with an optional "all" key for the aggregate score.
    """

    def grouped_metric(scores: list[SampleScore]) -> Value:
        # Satisfy the type checker that the metric is a MetricProtocol
        metric_protocol = cast(MetricProtocol, metric)

        # Slice the scores into groups
        scores_dict: dict[str, list[SampleScore]] = {}
        for sample_score in scores:
            if (
                sample_score.sample_metadata is None
                or group_key not in sample_score.sample_metadata
            ):
                raise ValueError(
                    f"Sample {sample_score.sample_id} has no {group_key} metadata. To compute a grouped metric each sample metadata must have a value for '{group_key}'"
                )
            group_name = str(sample_score.sample_metadata.get(group_key))
            if group_name not in scores_dict:
                scores_dict[group_name] = []
            scores_dict[group_name].append(sample_score)

        # Compute the per group metric
        grouped_scores = {
            group_name: metric_protocol(values)
            for group_name, values in scores_dict.items()
        }

        if not all:
            return cast(Value, grouped_scores)
        else:
            # Compute the all metric
            all_group_metric = None
            if all == "samples":
                # samples means apply the metric to all samples
                all_group_metric = metric_protocol(scores)
            elif all == "groups":
                # group means the overall score is the mean of all the group scores
                all_group_metric = np.mean(
                    [value_to_float(val) for val in grouped_scores.values()]
                ).item()

            return cast(Value, {**grouped_scores, all_label: all_group_metric})

    return grouped_metric
