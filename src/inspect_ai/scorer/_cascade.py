from math import isnan

from inspect_ai.solver._task_state import TaskState

from ._metric import Score, value_to_float
from ._metrics.accuracy import accuracy
from ._metrics.std import stderr
from ._scorer import Scorer, scorer
from ._target import Target


@scorer(metrics=[accuracy(), stderr()])
def cascade(threshold: float = 1.0, **scorers: Scorer) -> Scorer:
    r"""Score with each scorer in turn, stopping at the first that settles.

    Runs `scorers` in the order given, cheapest first, and short-circuits at
    the first stage whose score settles the sample, so later (typically more
    expensive) stages such as a grader model only run on samples the earlier
    stages did not settle. This complements `multi_scorer`, which runs every
    scorer concurrently and reduces their scores, and so cannot skip a stage
    based on a cheaper stage's result.

    Scorers are passed as keyword arguments so each stage is named explicitly
    rather than relying on the registry (a scorer is not guaranteed to be a
    registry object, and registry names are not always meaningful here).
    `**scorers` preserves call order, which is the order the stages run in.

    A stage *settles* the sample when `value_to_float` of its score is at least
    `threshold` (default `1.0`, i.e. a `CORRECT` verdict). A stage that
    declines (returns `None`) or is unscored (`nan`) is skipped and the cascade
    continues. If no stage settles, the last stage that produced a real score
    is returned; if no stage produced a real score (every stage declined or was
    unscored), the cascade returns `Score.unscored(reason="scoring_failed")`.
    The returned score is a copy of the settling stage's score with `decided_by`
    added to its metadata, naming the stage whose verdict is returned (the
    settling stage, or the last scored stage on fall-through); the sub-scorer's
    own `Score` object is not mutated.

    The cascade assumes earlier (cheaper) scorers do not produce false
    positives, so a `CORRECT` from exact match or symbolic equivalence can be
    trusted without running the grader model. That assumption is the caller's
    to uphold. `value_to_float` warns and returns `0` for list/dict values, so
    cascade is intended for scalar `CORRECT`/`INCORRECT`-style scorers.

    Args:
        threshold: Minimum `value_to_float` score for a stage to settle the
            sample and short-circuit the remaining stages. Defaults to `1.0`.
        **scorers: Named scorers, run in the order given. A stage cannot be
            named `threshold`, which is a reserved parameter.

    Returns:
        A Scorer that reports the settling stage's score.
    """
    to_float = value_to_float()

    async def score(state: TaskState, target: Target) -> Score:
        last_scored: tuple[str, Score] | None = None
        for name, sub_scorer in scorers.items():
            result = await sub_scorer(state, target)
            if result is None:
                continue
            value = to_float(result.value)
            if isnan(value):
                continue
            last_scored = (name, result)
            if value >= threshold:
                break

        if last_scored is None:
            return Score.unscored(reason="scoring_failed")

        decided_by, result = last_scored
        return result.model_copy(
            update={"metadata": (result.metadata or {}) | {"decided_by": decided_by}}
        )

    return score
