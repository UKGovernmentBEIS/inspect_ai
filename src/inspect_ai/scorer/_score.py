from contextvars import ContextVar
from copy import copy

from inspect_ai.model._conversation import ModelConversation
from inspect_ai.solver._task_state import TaskState, sample_state

from ._metric import Score
from ._scorer import Scorer
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
    from inspect_ai.log._transcript import ScoreEvent, transcript

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
    target = _target.get(None)
    if scorers is None or target is None:
        raise RuntimeError(
            "The score() function can only be called while executing a task with a scorer."
        )

    scores: list[Score] = []
    for scorer in scorers:
        score = await scorer(state, target)
        scores.append(score)
        transcript()._event(
            ScoreEvent(score=score, target=target.target, intermediate=True)
        )

    return scores


def init_scoring_context(scorers: list[Scorer], target: Target) -> None:
    _scorers.set(scorers)
    _target.set(target)


_scorers: ContextVar[list[Scorer]] = ContextVar("scorers")
_target: ContextVar[Target] = ContextVar("target")
