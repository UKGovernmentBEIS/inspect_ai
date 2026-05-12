import math
import re
from typing import Callable, Literal

from inspect_ai._util.text import (
    str_to_float,
    strip_numeric_punctuation,
    strip_punctuation,
)
from inspect_ai.scorer._unicode import unicode_number_to_float
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
                return Score(
                    value=CORRECT, answer=answer, explanation=state.output.completion
                )

        return Score(
            value=INCORRECT, answer=answer, explanation=state.output.completion
        )

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
    if numeric and _is_number(strip_numeric_punctuation(t)):
        # the target is a number: extract the relevant number(s) from the
        # value, normalize both, and compare for numeric equality. we do
        # NOT fall through to the text comparison below because e.g.
        # "25".endswith("5") is True but 25 != 5.
        v = strip_numeric_punctuation(v)
        t = normalize_number(strip_numeric_punctuation(t))
        words = re.split(r"\s+", v)
        if location == "begin":
            v = first_number_normalized(words)
        elif location == "end":
            words.reverse()
            v = first_number_normalized(words)
        elif location == "exact":
            v = normalize_number(v)
        else:
            # location == "any": match if any number in the value equals t
            numbers = all_numbers_normalized(words)
            return answer, t in numbers
        answer = v
        return answer, v == t
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


def _is_number(s: str) -> bool:
    """Is `s` parseable as a finite number?

    Recognises ordinary float syntax (including signs, decimals, and
    exponents, e.g. ``-5``, ``3.14``, ``1e3``) as well as unicode numeric
    characters (e.g. ``½``, ``三``, ``5²``) that ``str.isnumeric`` accepts
    but ``float`` rejects. ``nan`` and ``inf`` are not considered numbers.
    """
    try:
        return math.isfinite(float(s))
    except ValueError:
        return s.isnumeric()


def first_number_normalized(words: list[str]) -> str:
    number = next((word for word in words if _is_number(word)), words[0])
    return normalize_number(number)


def all_numbers_normalized(words: list[str]) -> list[str]:
    return [normalize_number(word) for word in words if _is_number(word)]


def normalize_number(number: str, precision: int = 5) -> str:
    num = _parse_number(number)
    if num is not None and math.isfinite(num):
        return format(num, f".{precision}g")
    else:
        return number


def _parse_number(number: str) -> float | None:
    # first try the built-in float parser (which handles signs, decimals,
    # and exponents); if that fails, try our extended parsers for unicode
    # superscripts/fractions and finally generic unicode numeric characters
    for parse in (float, str_to_float, unicode_number_to_float):
        try:
            return parse(number)
        except ValueError:
            pass
    return None
