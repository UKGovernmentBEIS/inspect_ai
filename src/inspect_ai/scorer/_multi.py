import asyncio

from inspect_ai.solver import TaskState

from ._metric import Score
from ._reducer import ScoreReducer
from ._scorer import Scorer
from ._target import Target


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
