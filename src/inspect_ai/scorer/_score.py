from contextvars import ContextVar

from inspect_ai.solver._task_state import TaskState

from ._metric import Score
from ._scorer import Scorer
from ._target import Target


async def score(state: TaskState) -> list[Score]:
    scorers = _scorers.get(None)
    target = _target.get(None)
    if scorers is None or target is None:
        raise RuntimeError(
            "The score() function can only be called while executing a scored task."
        )

    return [await scorer(state, target) for scorer in scorers]


def init_scoring_context(scorers: list[Scorer], target: Target) -> None:
    _scorers.set(scorers)
    _target.set(target)


_scorers: ContextVar[list[Scorer]] = ContextVar("scorers")
_target: ContextVar[Target] = ContextVar("target")
