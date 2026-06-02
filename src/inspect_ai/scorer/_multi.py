"""Multi-scorer: run N scorers in parallel and reduce to one Score."""

import asyncio
from typing import Sequence

from inspect_ai._util.registry import RegistryInfo, registry_tag
from inspect_ai.scorer._metric import Metric, Score
from inspect_ai.scorer._reducer import ScoreReducer, reducer_create
from inspect_ai.scorer._scorer import (
    SCORER_METRICS,
    Scorer,
    scorer_metrics,
    scorer_register,
)
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState


def multi_scorer(
    scorers: Sequence[Scorer],
    reducer: ScoreReducer | str = "mean",
) -> Scorer:
    """Returns a Scorer that runs multiple Scorers in parallel and aggregates
    their results into a single Score using the provided reducer function.

    Args:
        scorers: Two or more scorers to run in parallel.
        reducer: Reducer to aggregate scores.  Can be a :class:`ScoreReducer`
            callable or a string name of a registered reducer
            (``"mean"``, ``"mode"``, ``"median"``).  Defaults to ``"mean"``.

    Returns:
        A :class:`Scorer` with registry info attached (so it can be used
        directly in ``Task(scorer=multi_scorer(...))``.

    Raises:
        ValueError: If ``scorers`` is empty.
    """
    if not scorers:
        raise ValueError("multi_scorer requires at least one scorer.")

    resolved_reducer: ScoreReducer = (
        reducer if callable(reducer) else reducer_create(reducer)
    )

    async def score(state: TaskState, target: Target) -> Score | None:
        results = await asyncio.gather(*[s(state, target) for s in scorers])
        valid = [s for s in results if s is not None]
        return resolved_reducer(valid) if valid else None

    # -------------------------------------------------------------------------
    # FIX for https://github.com/UKGovernmentBEIS/inspect_ai/issues/4027
    #
    # The bare `score` closure above has no registry info. Every scorer that
    # goes through the `@scorer` decorator gets `registry_tag` called on its
    # instance inside `scorer_wrapper` (_scorer.py ~L155-170).  We must do the
    # same here so that `_eval/task/run.py`'s call to `registry_info(scorer)`
    # does not raise "Object score does not have registry info".
    #
    # Steps:
    #   1. Register the *factory* function once (idempotent) so it appears in
    #      the scorer registry and `registry_tag` can look it up.
    #   2. Tag the concrete `score` closure with RegistryInfo and the
    #      constructor arguments so `registry_params` can recover them for
    #      ScorerSpec serialisation.
    # -------------------------------------------------------------------------

    # Step 1 – register the factory (idempotent; only writes if not present).
    scorer_register(multi_scorer, name="multi_scorer")  # type: ignore[arg-type]

    # Step 2 – tag the closure instance.
    registry_tag(
        multi_scorer,  # factory used as template key
        score,         # instance to tag
        RegistryInfo(
            type="scorer",
            name="multi_scorer",
            metadata={SCORER_METRICS: _combined_metrics(scorers)},
        ),
        scorers,       # positional arg — stored for replay
        reducer,       # positional arg — stored for replay
    )

    return score  # type: ignore[return-value]


def _combined_metrics(scorers: Sequence[Scorer]) -> list[Metric]:
    """Collect and deduplicate metrics from all child scorers.

    Returns an empty list when child scorers carry no metrics (which is the
    safe/neutral default — multi_scorer itself does not compute aggregate
    metrics over samples; that's handled by the individual child scorers'
    own metric lists when the Task uses a list-of-scorers pattern).
    """
    seen: set[str] = set()
    result: list[Metric] = []
    for s in scorers:
        try:
            for m in scorer_metrics(s):
                if isinstance(m, dict):
                    continue  # grouped metrics — skip for now
                name = getattr(m, "__name__", repr(m))
                if name not in seen:
                    seen.add(name)
                    result.append(m)  # type: ignore[arg-type]
        except Exception:
            # scorer_metrics raises if the scorer has no registry info
            # (e.g. it was constructed outside of @scorer).  Skip silently.
            pass
    return result
