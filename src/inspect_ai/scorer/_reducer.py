from collections import Counter

from inspect_ai.scorer._metric import Score, ValueToFloat, value_to_float
from inspect_ai.scorer._scorer import ScoreReducer


def majority() -> ScoreReducer:
    def majority_reducer(scores: list[Score]) -> Score:
        r"""A utility function for taking a majority vote over a list of scores.

        Args:
            scores: a list of Scores.
        """
        counts: Counter[str | int | float | bool] = Counter()
        for score in scores:
            counts[score._as_scalar()] += 1
        return Score(
            value=counts.most_common(1)[0][0],
            answer=scores[0].answer,
            explanation=scores[0].explanation,
            metadata={
                "individual_scores": scores
            },  # TODO: massage into format better for display
        )

    return majority_reducer


def avg(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer:
    def avg_reducer(scores: list[Score]) -> Score:
        r"""A utility function for taking a mean value over a list of scores.

        Args:
            scores: a list of Scores.
        """
        sum = 0.0
        for score in scores:
            sum += value_to_float(score.value)
        return Score(
            value=sum / len(scores),
            answer=scores[0].answer,
            explanation=scores[0].explanation,
            metadata={
                "individual_scores": scores
            },  # TODO: massage into format better for display
        )

    return avg_reducer
