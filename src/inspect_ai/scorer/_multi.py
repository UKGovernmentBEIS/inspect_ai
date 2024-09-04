import asyncio

from inspect_ai.scorer._reducer.registry import create_reducers
from inspect_ai.solver._task_state import TaskState

from ._metric import Score
from ._reducer.types import ScoreReducer
from ._scorer import Scorer
from ._target import Target


def multi_scorer(scorers: list[Scorer], reducer: str | ScoreReducer) -> Scorer:
    r"""Returns a Scorer that runs multiple Scorers in parallel and aggregates their results into a single Score using the provided reducer function.

    Args:
        scorers: a list of Scorers.
        reducer: a function which takes in a list of Scores and returns a single Score.
    """
    reducer = create_reducers(reducer)[0]

    async def score(state: TaskState, target: Target) -> Score:
        scores = await asyncio.gather(*[_scorer(state, target) for _scorer in scorers])
        return reducer(scores)

    return score
