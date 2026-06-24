"""Probe a model's response distribution on a balanced binary prompt.

Run with:
    inspect eval examples/token_preference_probe.py --model openai/gpt-4o --temperature 1 --epochs 50
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Scorer, Target, frequency, scorer
from inspect_ai.solver import TaskState, generate

COIN_FLIP_PROMPT = (
    "Flip a fair coin and report the result. "
    "Respond with only 'Heads' or 'Tails', nothing else."
)


def _coin_flip_category(completion: str) -> str:
    answer = completion.strip().lower().strip(" .")
    if answer == "heads":
        return "heads"
    if answer == "tails":
        return "tails"
    return "other"


@scorer(metrics=[frequency(categories=["heads", "tails", "other"])])
def coin_flip_distribution() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        answer = _coin_flip_category(state.output.completion)
        return Score(value=answer, answer=answer)

    return score


@task
def token_preference_probe() -> Task:
    return Task(
        dataset=[Sample(input=COIN_FLIP_PROMPT)],
        solver=generate(),
        scorer=coin_flip_distribution(),
    )
