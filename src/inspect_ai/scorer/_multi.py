import asyncio
from collections import Counter
from typing import (
    Protocol,
    runtime_checkable,
)

from inspect_ai.solver import TaskState

from ._metric import Score
from ._scorer import Scorer
from ._target import Target


@runtime_checkable
class ScoreReducer(Protocol):
    def __call__(self, scores: list[Score]) -> Score: ...


def multi_scorer(scorers: list[Scorer], reducer: ScoreReducer) -> Scorer:
    r"""Returns a Scorer that runs multiple Scorers in parallel and aggregates their results into a single Score using the provided reducer function.

    Args:
        scorers: a list of Scorers.
        reducer: a function which takes in a list of Scores and returns a single Score.
    """

    async def score(state: TaskState, target: Target) -> Score:
        scores = await asyncio.gather(*[_scorer(state, target) for _scorer in scorers])
        return reducer(scores)

    return score


def majority_vote(scores: list[Score]) -> Score:
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
