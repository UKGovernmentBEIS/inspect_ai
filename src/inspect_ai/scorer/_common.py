from typing import Callable, Literal

from inspect_ai._util.text import strip_numeric_punctuation, strip_punctuation
from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._scorer import Scorer
from ._target import Target


def str_match_scorer(match: Callable[[str, str], tuple[str, bool]]) -> Scorer:
    """Scorer that uses a matching function.

    The matching function returns tuple[str,bool], where str is the answer
    extracted from the model output and bool is whether it matched the target
    """

    async def score(state: TaskState, target: Target) -> Score:
        answer: str | None = None
        for value in target:
            answer, matched = match(state.output.completion, value)
            if matched:
                explanation = (
                    state.output.completion
                    if state.output.completion != answer
                    else None
                )
                return Score(
                    value=CORRECT, answer=answer, explanation=state.output.completion
                )

        explanation = (
            state.output.completion if state.output.completion != answer else None
        )
        return Score(value=INCORRECT, answer=answer, explanation=explanation)

    return score


def match_str(
    value: str,
    target: str,
    location: Literal["begin", "end", "any", "exact"] = "end",
    ignore_case: bool = True,
    ignore_punctuation: bool = True,
    numeric: bool = False,
) -> tuple[str, bool]:
    # strip ws
    v = value.strip()
    t = target.strip()

    # baseline answer (will only change for numeric)
    answer = v

    # further cleanup
    if ignore_case:
        v = v.casefold()
        t = t.casefold()
    if numeric:
        # remove punctuation
        v = strip_numeric_punctuation(v)
        t = strip_numeric_punctuation(t)
        # normalize as required
        t = normalize_number(t)
        if location == "begin":
            words = v.split(" ")
            v = first_number_normalized(words)
        elif location == "end":
            words = v.split(" ")
            words.reverse()
            v = first_number_normalized(words)
        elif location == "exact":
            v = normalize_number(v)
        answer = v
    elif ignore_punctuation:
        v = strip_punctuation(v)
        t = strip_punctuation(t)

    # comparisons
    if location == "begin":
        return answer, v.startswith(t)
    elif location == "end":
        return answer, v.endswith(t)
    elif location == "exact":
        return answer, v == t
    else:
        return answer, t in v


def first_number_normalized(words: list[str]) -> str:
    number = next(
        (word for word in words if word.replace(".", "").isnumeric()), words[0]
    )
    return normalize_number(number)


def normalize_number(number: str, precision: int = 5) -> str:
    if number.replace(".", "").isnumeric():
        num = float(number)
        return format(num, f".{precision}g")
    else:
        return number
