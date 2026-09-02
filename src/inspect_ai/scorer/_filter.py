import inspect
from typing import Awaitable, Callable

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import (
    is_registry_object,
    registry_info,
    registry_params,
    set_registry_info,
    set_registry_params,
)
from inspect_ai.solver._task_state import TaskState

from ._metric import Score
from ._scorer import Scorer
from ._target import Target


def filter_scorer(
    scorer: Scorer,
    predicate: Callable[[TaskState, Target], bool | Awaitable[bool]],
) -> Scorer:
    r"""Restrict a scorer to the samples a predicate selects.

    Calls `predicate(state, target)` for each sample; when it returns `False`
    the sample is left unscored by this scorer (the scorer returns `None` and
    the inner scorer is not called), otherwise scoring is delegated to the
    inner scorer. Use this to avoid spending grader-model calls on samples
    that do not need them — e.g. transcripts the solver marked as degenerate,
    or a kind of sample this scorer does not apply to.

    The returned scorer keeps the inner scorer's identity: it is recorded in
    the log under the inner scorer's name with the inner scorer's options and
    metrics, so persisted scores and metrics aggregation are unchanged. The
    only trace of the filter is a `filter` key in the scorer's metadata naming
    the predicate (use a named function rather than a lambda for a readable
    entry). Two filtered scorers with different inner scorers therefore coexist
    under their own names, and a filtered scorer alongside an unfiltered one of
    the same kind is disambiguated exactly as two unfiltered ones would be.

    The predicate itself is not persisted: re-scoring the log with
    `inspect score` re-creates the inner scorer from its recorded name and
    options and runs it on every sample.

    Filtered-out samples have no score from this scorer, so they are excluded
    from this scorer's metrics rather than counted as zero (metrics are
    computed over the samples that have a score for the scorer). Other
    scorers in the task still score them as usual.

    Args:
        scorer: Scorer to run on the selected samples. Must be a registry
            object (created by a function decorated with `@scorer`).
        predicate: Called with the sample's `TaskState` and `Target`; return
            `True` to score the sample, `False` to skip it. May be `async`.

    Returns:
        A Scorer that scores only the samples the predicate selects.
    """
    if not is_registry_object(scorer, type="scorer"):
        raise PrerequisiteError(
            f"The scorer {getattr(scorer, '__name__', '<unknown>')} was not created "
            "by a function decorated with @scorer so cannot be filtered."
        )

    async def score(state: TaskState, target: Target) -> Score | None:
        selected = predicate(state, target)
        if inspect.isawaitable(selected):
            selected = await selected
        if not selected:
            return None
        return await scorer(state, target)

    predicate_name = getattr(predicate, "__name__", type(predicate).__name__)
    info = registry_info(scorer)
    set_registry_info(
        score,
        info.model_copy(
            update={"metadata": info.metadata | {"filter": predicate_name}}
        ),
    )
    set_registry_params(score, registry_params(scorer))
    return score
