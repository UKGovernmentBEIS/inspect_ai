import re
from typing import Any

from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target


def match_target(match: str, target: Target, ignore_case: bool) -> bool:
    if ignore_case:
        match = match.lower()
        target = Target([t.lower() for t in target])

    return match in target


def match_first(
    matches: tuple[str | Any, ...], target: Target, ignore_case: bool
) -> str | None:
    for match in matches:
        if not isinstance(match, str):
            continue

        if match_target(match, target, ignore_case):
            return match

    return None


def match_all_groups(
    matches: tuple[str | Any, ...], target: Target, ignore_case: bool
) -> str | None:
    for match in matches:
        if not isinstance(match, str):
            continue

        if not match_target(match, target, ignore_case):
            return None

    return target.text


@scorer(metrics=[accuracy(), stderr()])
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
            groups = match.groups()
            if match_all:
                found_match = match_all_groups(
                    matches=groups, target=target, ignore_case=ignore_case
                )
                answer = found_match
            else:
                found_match = match_first(
                    matches=groups, target=target, ignore_case=ignore_case
                )

                if found_match is None and len(groups) == 1:
                    # A common use of a pattern is to extract a single answer
                    # from some templated text. If we fail to match in that
                    # scenario, it's worth returning the failed match because
                    # this is useful information for the user.
                    answer = groups[0]
                else:
                    answer = found_match

            return Score(
                value=CORRECT if found_match else INCORRECT,
                answer=answer,
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
