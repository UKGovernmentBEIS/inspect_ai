from enum import Enum
from typing import Literal

from inspect_ai._util.pattern import (
    ANSWER_PATTERN_LETTER,
    ANSWER_PATTERN_LINE,
    ANSWER_PATTERN_WORD,
)

from ._metrics import accuracy, stderr
from ._pattern import pattern
from ._scorer import Scorer, scorer


class AnswerPattern(str, Enum):
    """Regular expressions for extracting answers from output.

    These expressions act on output prefixed with "ANSWER: ".
    """

    LETTER = ANSWER_PATTERN_LETTER
    """Extracts a single letter (used with multiple choice)."""

    WORD = ANSWER_PATTERN_WORD
    """Extracts one or more word characters (used for yes/no output)."""

    LINE = ANSWER_PATTERN_LINE
    """Extracts the rest of the line after ANSWER: (used for more complex output).

    Note that when using a LINE pattern your prompt should instruct the
    model to answer with a separate line at the end.
    """


@scorer(metrics=[accuracy(), stderr()])
def answer(type: Literal["letter", "word", "line"]) -> Scorer:
    """Scorer for model output that preceded answers with ANSWER:.

    Some solvers including multiple_choice solicit answers from
    the model prefaced with "ANSWER:". This scorer extracts
    answers of this form for comparison with the target.

    Note that you must specify a `type` for the answer scorer.

    Args:
      type: (Literal["letter", "word", "line"]): Type of answer
        to extract. "letter" is used with multiple choice and
        extracts a single letter; "word" will extract the next
        word (often used for yes/no answers); "line" will take
        the rest of the line (used for more more complex answers
        that may have embedded spaces). Note that when using
        "line" your prompt should instruct the model to answer
        with a separate line at the end.

    """
    match type:
        case "letter":
            return pattern(AnswerPattern.LETTER)
        case "word":
            return pattern(AnswerPattern.WORD)
        case "line":
            return pattern(AnswerPattern.LINE)
