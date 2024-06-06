import re
from typing import Any

from inspect_ai.solver import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, bootstrap_std
from ._scorer import Scorer, scorer
from ._target import Target


def match_first(
    matches: tuple[str | Any, ...], target: Target, ignore_case: bool
) -> str | None:
    for match in matches:
        if isinstance(match, str):
            if ignore_case:
                match = match.lower()

            if match in target:
                return match

    return None


def match_all_groups(
    matches: tuple[str | Any, ...], target: Target, ignore_case: bool
) -> str | None:
    for match in matches:
        if isinstance(match, str):
            if ignore_case:
                match = match.lower()

            if match not in target:
                return None

    return target.text


@scorer(metrics=[accuracy(), bootstrap_std()])
def pattern(pattern: str, ignore_case: bool = True, match_all: bool = False) -> Scorer:
    """Scorer which extracts the model answer using a regex.

    Note that at least one regex group is required to match
    against the target.

    The regex can have a single capture group or multiple groups.
    In the case of multiple groups, the scorer can be configured
    to match either one or all of the extracted groups

    Args:
       pattern (str): Regular expression for extracting the
          answer from model output.
       ignore_case (bool): Ignore case when comparing
          the extract answer to the targets. (Default: True)
       match_all (bool): With multiple captures, do all captured
          values need to match the target? (Default: False)
    """

    async def score(state: TaskState, target: Target) -> Score:
        # extract the answer
        match = re.search(
            pattern, state.output.completion, re.IGNORECASE if ignore_case else 0
        )

        if match:
            if ignore_case:
                target = Target([t.lower() for t in target])

            if match_all:
                found_match = match_all_groups(
                    matches=match.groups(), target=target, ignore_case=ignore_case
                )
            else:
                found_match = match_first(
                    matches=match.groups(), target=target, ignore_case=ignore_case
                )

            return Score(
                value=CORRECT if found_match else INCORRECT,
                answer=found_match,
                explanation=state.output.completion,
            )
        else:
            # didn't find the scoring pattern
            return Score(
                value=INCORRECT,
                explanation="Scoring pattern not matched in output: "
                + f"{state.output.completion}",
            )

    return score
