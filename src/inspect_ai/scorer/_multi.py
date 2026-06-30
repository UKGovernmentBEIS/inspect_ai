import functools

from inspect_ai._util._async import tg_collect
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_name,
    registry_tag,
)
from inspect_ai.scorer._reducer.registry import create_reducers
from inspect_ai.solver._task_state import TaskState

from ._metric import Metric, Score
from ._reducer.types import ScoreReducer
from ._scorer import SCORER_METRICS, Scorer, scorer_metrics, scorer_register
from ._target import Target


def multi_scorer(scorers: list[Scorer], reducer: str | ScoreReducer) -> Scorer:
    r"""Returns a Scorer that runs multiple Scorers in parallel and aggregates their results into a single Score using the provided reducer function.

    Args:
        scorers: a list of Scorers.
        reducer: a function which takes in a list of Scores and returns a single Score.
    """
    reducer_spec = reducer
    reducer = create_reducers(reducer)[0]
    scorer_name = registry_name(multi_scorer, "multi_scorer")

    async def score(state: TaskState, target: Target) -> Score:
        scores = await tg_collect(
            [functools.partial(_scorer, state, target) for _scorer in scorers]
        )
        # Filter out None values from scores list
        resolved_scores = [score for score in scores if score is not None]
        if len(resolved_scores) == 0:
            # every sub-scorer declined to score; reducers index scores[0]
            # so surface the unscored sentinel rather than crashing
            return Score.unscored()
        return reducer(resolved_scores)

    registry_tag(
        multi_scorer,
        score,
        RegistryInfo(
            type="scorer",
            name=scorer_name,
            metadata={SCORER_METRICS: _multi_scorer_metrics(scorers)},
        ),
        scorers,
        reducer_spec,
    )
    return score


def _multi_scorer_metrics(
    scorers: list[Scorer],
) -> list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]]:
    for scorer in scorers:
        if is_registry_object(scorer, type="scorer"):
            return scorer_metrics(scorer)
    return []


scorer_register(
    multi_scorer,
    name=registry_name(multi_scorer, "multi_scorer"),
    metadata={SCORER_METRICS: []},
)
