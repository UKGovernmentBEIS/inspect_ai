from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState


@scorer(metrics=[accuracy(), stderr()])
def simple_score(ignore_case: bool = True):
    async def score(state: TaskState, target: Target):
        # check for correct
        answer = state.output.completion
        text = target.text
        if ignore_case:
            correct = answer.lower().rfind(text.lower()) != -1
        else:
            correct = answer.rfind(text) != -1

        # return score
        return Score(value=CORRECT if correct else INCORRECT, answer=answer)

    return score
