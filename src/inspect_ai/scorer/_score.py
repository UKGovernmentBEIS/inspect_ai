from contextvars import ContextVar
from copy import copy

from inspect_ai._sentinel._scope import AgentScope, sentinel_scope
from inspect_ai._util.registry import has_registry_params, registry_params
from inspect_ai.model._conversation import ModelConversation
from inspect_ai.model._model import sample_model_usage, sample_role_usage
from inspect_ai.solver._task_state import TaskState, sample_state

from ._metric import Score
from ._scorer import Scorer, unique_scorer_name
from ._target import Target


async def score(conversation: ModelConversation) -> list[Score]:
    """Score a model conversation.

    Score a model conversation (you may pass `TaskState` or `AgentState`
    as the value for `conversation`)

    Args:
      conversation: Conversation to submit for scoring.
        Note that both `TaskState` and `AgentState` can be passed
        as the `conversation` parameter.

    Returns:
      List of scores (one for each task scorer)

    Raises:
      RuntimeError: If called from outside a task or within
        a task that does not have a scorer.

    """
    from inspect_ai.event._score import ScoreEvent
    from inspect_ai.log._transcript import transcript

    # get TaskState (if the `conversation` is a `TaskState` use it directly,
    # otherwise synthesize one)
    if isinstance(conversation, TaskState):
        state = conversation
    else:
        current_state = sample_state()
        if current_state is None:
            raise RuntimeError(
                "The score() function can only be called while executing a task"
            )
        state = copy(current_state)
        state.messages = conversation.messages
        state.output = conversation.output

    # get current scorers and target
    scorers = _scorers.get(None)
    scorer_names = _scorer_names.get(None)
    target = _target.get(None)
    if scorers is None or scorer_names is None or target is None:
        raise RuntimeError(
            "The score() function can only be called while executing a task with a scorer."
        )

    scores: list[Score] = []
    for scorer, scorer_name in zip(scorers, scorer_names, strict=True):
        with sentinel_scope(AgentScope.OFF, final=True):
            score = await scorer(state, target)
        if score is not None:
            scores.append(score)
            transcript()._event(
                ScoreEvent(
                    score=score,
                    target=target.target,
                    intermediate=True,
                    scorer=scorer_name,
                    scorer_args=registry_params(scorer)
                    if has_registry_params(scorer)
                    else None,
                    model_usage=sample_model_usage() or None,
                    role_usage=sample_role_usage() or None,
                )
            )

    return scores


def init_scoring_context(
    scorers: list[Scorer], target: Target, scorer_names: list[str] | None = None
) -> None:
    """Bind the scorers `score()` runs, with the score name of each.

    `scorer_names` are the names final scoring uses, so intermediate score
    events carry the same names as the sample's scores. Names are generated
    from the scorers when it is omitted.
    """
    if scorer_names is None:
        scorer_names = []
        for scorer in scorers:
            scorer_names.append(unique_scorer_name(scorer, scorer_names))
    _scorers.set(scorers)
    _scorer_names.set(scorer_names)
    _target.set(target)


_scorers: ContextVar[list[Scorer]] = ContextVar("scorers")
_scorer_names: ContextVar[list[str]] = ContextVar("scorer_names")
_target: ContextVar[Target] = ContextVar("target")
