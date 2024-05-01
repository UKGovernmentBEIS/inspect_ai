import re

from inspect_ai.solver import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, bootstrap_std
from ._scorer import Scorer, Target, scorer


@scorer(metrics=[accuracy(), bootstrap_std()])
def pattern(pattern: str, ignore_case: bool = True) -> Scorer:
    """Scorer which extracts the model answer using a regex.

    The regex can have a single capture group or multiple
    groups. In the case of multiple groups, the first
    group is bypassed (as the prefix of the answer) and
    the second group is used for the answer.

    Args:
       pattern (str): Regular expression for extracting the
          answer from model output.
       ignore_case (bool): Ignore case when comparing
          the extract answer to the targets.
    """

    async def score(state: TaskState, target: Target) -> Score:
        # extract the answer
        match = re.search(
            pattern, state.output.completion, re.IGNORECASE if ignore_case else 0
        )

        # got a match
        if match:
            # handle case insentitive
            answer = match.group(1) if len(match.groups()) == 1 else match.group(2)
            input = answer
            if ignore_case:
                input = input.lower()
                target = Target([t.lower() for t in target])

            # return score
            return Score(
                value=CORRECT if input in target else INCORRECT,
                answer=answer,
                explanation=state.output.completion,
            )
        # didn't find the scoring pattern
        else:
            return Score(
                value=INCORRECT,
                explanation="Scoring pattern not matched in output: "
                + f"{state.output.completion}",
            )

    return score
