import math
import re
from typing import Callable, Literal

from inspect_ai._util.text import (
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
    if numeric:
        t = strip_numeric_punctuation(t)
    if numeric and _is_number(t):
        # the target is a number: extract the relevant number(s) from the
        # value, normalize both, and compare for numeric equality. we do
        # NOT fall through to the text comparison below because e.g.
        # "25".endswith("5") is True but 25 != 5.
        v = strip_numeric_punctuation(v)
        t = normalize_number(t)
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
            for number in all_numbers_normalized(words):
                if number == t:
                    return number, True
            return answer, False
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


def _parse_number(s: str) -> float | None:
    """Parse `s` as a finite number, or None.

    Recognises plain float syntax (signs, decimals, exponents) and the
    full set of inputs handled by ``unicode_number_to_float`` (unicode
    minus, vulgar fractions, superscripts, Chinese numerals, fullwidth
    digits, locale grouping). Rejects strings with trailing non-numeric
    content (so ``"5 some text"`` returns None) so that ``location="exact"``
    stays actually exact. ``nan`` and ``inf`` also return None.
    """
    for parse in (float, unicode_number_to_float):
        try:
            num = parse(s)
        except ValueError:
            continue
        if math.isfinite(num):
            return num
    return None


def _is_number(s: str) -> bool:
    return _parse_number(s) is not None


def first_number_normalized(words: list[str]) -> str:
    number = next((word for word in words if _is_number(word)), None)
    return normalize_number(number) if number is not None else ""


def all_numbers_normalized(words: list[str]) -> list[str]:
    return [normalize_number(word) for word in words if _is_number(word)]


def normalize_number(number: str, precision: int = 5) -> str:
    num = _parse_number(number)
    if num is None:
        return number
    return format(num, f".{precision}g")
