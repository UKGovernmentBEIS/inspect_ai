"""Demo of categorical scorers using frequency() / categorical() metrics.

Run with:
    uv run inspect eval examples/categorical_demo.py --model mockllm/model

Then open the viewer to compare how each scorer renders:

* ``verdict``           — single string-valued categorical score
* ``behaviour``         — dict of two independent categorical dimensions
* ``verdict_one_hot``   — the old one-hot-dict pattern, for comparison
"""

import random

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    Score,
    Scorer,
    StrEnum,
    Target,
    accuracy,
    categorical,
    scorer,
)
from inspect_ai.solver import TaskState, generate


class Verdict(StrEnum):
    YES = "yes"
    NO = "no"
    UNSURE = "unsure"


class SabotageType(StrEnum):
    NONE = "none"
    SUBTLE = "subtle"
    OVERT = "overt"


# weight the random draws so the headline numbers aren't uniform
_VERDICT_WEIGHTS = {Verdict.YES: 0.55, Verdict.NO: 0.30, Verdict.UNSURE: 0.15}
_SABOTAGE_WEIGHTS = {
    SabotageType.NONE: 0.60,
    SabotageType.SUBTLE: 0.30,
    SabotageType.OVERT: 0.10,
}


def _draw_verdict(seed: int) -> Verdict:
    rng = random.Random(seed)
    return rng.choices(list(Verdict), weights=list(_VERDICT_WEIGHTS.values()))[0]


def _draw_sabotage(seed: int) -> SabotageType:
    rng = random.Random(seed)
    return rng.choices(list(SabotageType), weights=list(_SABOTAGE_WEIGHTS.values()))[0]


@scorer(metrics=categorical(Verdict))
def verdict() -> Scorer:
    """Single categorical score: value is one of yes/no/unsure."""

    async def score(state: TaskState, target: Target) -> Score:
        v = _draw_verdict(hash((state.sample_id, state.epoch)))
        return Score(
            value=v,
            answer=v,
            explanation=f"Grader judged the response as '{v}'.",
        )

    return score


@scorer(metrics={"*": categorical()})
def behaviour() -> Scorer:
    """Two independent categorical dimensions in a single dict-valued score."""

    async def score(state: TaskState, target: Target) -> Score:
        seed = hash((state.sample_id, state.epoch))
        sabotage = _draw_sabotage(seed)
        aware = _draw_verdict(seed * 31)
        return Score(
            value={"sabotage_type": sabotage, "eval_aware": aware},
            explanation=(
                f"Classified sabotage_type='{sabotage}', eval_aware='{aware}'."
            ),
        )

    return score


@scorer(metrics={"*": [accuracy()]})
def verdict_one_hot() -> Scorer:
    """Legacy one-hot encoding of the same verdict, for viewer comparison."""

    async def score(state: TaskState, target: Target) -> Score:
        v = _draw_verdict(hash((state.sample_id, state.epoch)))
        return Score(
            value={member.value: 1 if member is v else 0 for member in Verdict},
            answer=v,
        )

    return score


@task
def categorical_demo() -> Task:
    return Task(
        dataset=[Sample(input=f"Sample question {i}", target="yes") for i in range(40)],
        solver=generate(),
        scorer=[verdict(), behaviour(), verdict_one_hot()],
        epochs=3,
    )
