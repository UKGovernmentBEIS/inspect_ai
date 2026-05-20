from .._metric import Metric, SampleScore, metric


@metric
def mean() -> Metric:
    """Compute mean of all scores.

    Returns:
       mean metric
    """

    def metric(scores: list[SampleScore]) -> float:
        import numpy as np

        return np.mean([score.score.as_float() for score in scores]).item()

    return metric
