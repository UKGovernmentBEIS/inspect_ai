from typing import cast

import numpy as np

from .._metric import Metric, SampleScore, Value, metric


@metric
def mean() -> Metric:
    """Compute mean of all scores.

    Returns:
       mean metric
    """

    def metric(scores: list[SampleScore]) -> float:
        return np.mean([score.score.as_float() for score in scores]).item()

    return metric


@metric
def grouped_mean(group_key: str, all_name: str = "all") -> Metric:
    """Compute mean accross all scores, grouped by the `group` parameter.

    Args:
       group_key: The key in the sample metadata is use to select groups when
       grouping.
       all_name: The display name for the overall mean score (computed by taking the mean
       of the group means).

    Returns:
        grouped_mean metric
    """

    def metric(scores: list[SampleScore]) -> Value:
        scores_dict: dict[str, list[float]] = {}
        for sample_score in scores:
            if (
                sample_score.sample_metadata is None
                or group_key not in sample_score.sample_metadata
            ):
                raise ValueError(
                    f"Sample {sample_score.sample_id} has no {group_key} metadata. To compute `grouped_mean`each sample metadata must have a value for '{group_key}'"
                )
            group_name = str(sample_score.sample_metadata.get(group_key))
            if group_name not in scores_dict:
                scores_dict[group_name] = []
            scores_dict[group_name].append(sample_score.score.as_float())
        grouped_scores = {
            group_name: np.mean([val for val in values]).item()
            for group_name, values in scores_dict.items()
        }
        all_group_mean = np.mean([val for val in grouped_scores.values()]).item()
        return cast(Value, {**grouped_scores, all_name: all_group_mean})

    return metric
