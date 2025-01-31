import numpy as np

from .._metric import Metric, SampleScore, metric


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
def var() -> Metric:
    """Compute variance over all scores.

    Returns:
       var metric
    """

    def metric(scores: list[SampleScore]) -> float:
        return np.var([score.score.as_float() for score in scores]).item()

    return metric
