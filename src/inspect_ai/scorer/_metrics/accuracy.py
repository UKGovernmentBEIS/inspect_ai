from logging import getLogger

from .._metric import CORRECT, INCORRECT, PARTIAL, Metric, Score, Value, metric

logger = getLogger(__name__)


@metric
def accuracy(
    correct: Value = CORRECT,
    incorrect: Value = INCORRECT,
    partial: Value | None = PARTIAL,
) -> Metric:
    r"""Compute proportion of total answers which are correct.

    Args:
        correct (Value): Value that represents a correct answer.
        incorrect (Value): Value that represents an incorrect answer.
        partial (Value): Value to assign partial credit for

    Returns:
       Accuracy metric
    """

    def metric(scores: list[Score]) -> float:
        total_correct = 0.0
        total = float(len(scores))
        for item in scores:
            if item.value == correct:
                total_correct += 1
            elif item.value == partial:
                total_correct += 0.5
            elif item.value != incorrect:
                logger.warning(
                    "Unexpected item value for accuracy metric: {item.value}"
                )
        return total_correct / total

    return metric
