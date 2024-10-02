import logging
import re
import signal
from types import FrameType
from typing import Any, Literal, Type

from inspect_ai.dataset import Dataset, Sample
from inspect_ai.model import Model, get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    AnswerPattern,
    Score,
    Target,
)
from inspect_ai.solver import TaskState

logger = logging.getLogger(__name__)


def filter_dataset(
    dataset: Dataset,
    levels: list[Literal[1, 2, 3, 4, 5]] | Literal[1, 2, 3, 4, 5],
    subjects: list[str] | str,
) -> Dataset:
    """Filters the MATH dataset by levels and/or subjects.

    Arguments:
        dataset (Dataset): Dataset object to be filtered.
        levels (List): List of levels to filter on, 1 to 5.
        subjects (List): List of subjects to filter on.
    """
    # Filter dataset by levels, if required
    levels = levels if isinstance(levels, list) else [levels]
    levels_str = [str(elm) for elm in levels]
    if len(levels_str) > 0:
        dataset = dataset.filter(
            name=f"{dataset.name}_lvl-{'-'.join(levels_str)}",
            predicate=lambda sample: sample.metadata["level"] in levels_str
            if sample.metadata is not None
            else False,
        )

    # Filter dataset by subjects, if required
    subjects = subjects if isinstance(subjects, list) else [subjects]
    if len(subjects) > 0:
        dataset = dataset.filter(
            name=f"{dataset.name}_subject-{'-'.join(subjects)}",
            predicate=lambda sample: sample.metadata["subject"] in subjects
            if sample.metadata is not None
            else False,
        )

    return dataset


async def score_helper(
    state: TaskState,
    target: Target,
    exact_match: bool,
    use_sympy: bool = False,
    model: str | Model | None = None,
) -> Score:
    # Extract answer
    match = re.search(AnswerPattern.LINE, state.output.completion)
    if match:
        # Extract answer from the pattern
        answer = match.group(1)

        if exact_match:
            if use_sympy:
                # Use sympy library for exact match based on https://arxiv.org/pdf/2206.14858
                norm_answer = await normalize_final_answer(answer)
                norm_target = await normalize_final_answer(target.text)
                correct = await is_equiv_sympy(norm_answer, norm_target)
            else:
                correct = await is_equiv(answer, target.text)

        # Ask grader model to judge equivalence
        else:
            prompt = EQUIVALANCE_TEMPLATE % (
                {"expression1": target.text, "expression2": answer}
            )
            result = await get_model(model).generate(prompt)

            # Return the score
            correct = result.completion.lower() == "yes"

        score = Score(
            value=CORRECT if correct else INCORRECT,
            explanation=state.output.completion,
            metadata={
                "extracted_answer": answer,
            },
        )

        if not exact_match and score.metadata is not None:
            score.metadata.update({"grader_model_usage": result.usage})
    else:
        score = Score(
            value=INCORRECT,
            explanation="Answer not found in model output: "
            + f"{state.output.completion}",
        )

    return score


def record_to_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        input=record["problem"],
        target=remove_boxed(
            last_boxed_only_string(record["solution"]) or record["solution"]
        ),
        metadata={
            "level": record["level"].lower().lstrip("level "),
            "subject": record["type"].lower(),
            "solution": record["solution"],
        },
    )


def sample_to_fewshot(sample: Sample) -> str:
    # Based on https://arxiv.org/pdf/2206.14858 - Appendix D.2
    # Tags are capitalized to match the format of the user prompt
    prob_str = f"""PROBLEM:\n{sample.input}"""
    soln = sample.metadata["solution"] if sample.metadata is not None else None
    assert (
        soln is not None
    ), "Solution not found in sample, make sure to include it in the 'sample.metadata' dict."
    soln_str = f"""SOLUTION:\n{soln}"""
    ans_str = f"""ANSWER: {sample.target}"""

    # return fewshot (escaping {} used in latex to avoid interpretation as metadata variables)
    return f"""{prob_str}\n\n{soln_str}\n{ans_str}""".replace("{", "{{").replace(
        "}", "}}"
    )


# From here till normalize_final_answer() is borrowed from:
# https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/minerva_math/utils.py#L144
class timeout:
    def __init__(self, seconds: int = 1, error_message: str = "Timeout"):
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum: int, frame: FrameType | None) -> None:
        raise TimeoutError(self.error_message)

    def __enter__(self) -> None:
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: object | None,
    ) -> None:
        signal.alarm(0)


async def is_equiv_sympy(x1: str, x2: str) -> bool:
    """x1 and x2 are normalized latex string"""
    import sympy  # type: ignore
    from sympy.parsing.latex import parse_latex  # type: ignore

    try:
        with timeout(seconds=5):
            try:
                parsed_x1 = parse_latex(x1)
                parsed_x2 = parse_latex(x2)
            except (
                sympy.parsing.latex.errors.LaTeXParsingError,
                sympy.SympifyError,
                TypeError,
            ) as e:
                logger.debug(f"Couldn't parse one of {x1} or {x2}: {e}")
                return False

            try:
                diff = parsed_x1 - parsed_x2
            except TypeError:
                logger.debug(f"Couldn't subtract {x1} and {x2}")
                return False

            try:
                if sympy.simplify(diff) == 0:
                    return True
                else:
                    return False
            except ValueError:
                logger.debug(
                    f"Had some trouble simplifying when comparing {x1} and {x2}"
                )
                return False
    except TimeoutError:
        logger.debug(f"Timed out comparing {x1} and {x2}")
        return False
    except Exception as e:
        logger.debug(f"Failed comparing {x1} and {x2} with {e}")
        return False


async def normalize_final_answer(final_answer: str) -> str:
    """
    Normalize a final answer to a quantitative reasoning question.

    Copied character for character from appendix D of Lewkowycz et al. (2022)
    """
    final_answer = final_answer.split("=")[-1]

    for before, after in SUBSTITUTIONS:
        final_answer = final_answer.replace(before, after)
    for expr in REMOVED_EXPRESSIONS:
        final_answer = final_answer.replace(expr, "")

    # Extract answer that is in LaTeX math, is bold,
    # is surrounded by a box, etc.
    final_answer = re.sub(r"(.*?)(\$)(.*?)(\$)(.*)", "$\\3$", final_answer)
    final_answer = re.sub(r"(\\text\{)(.*?)(\})", "\\2", final_answer)
    final_answer = re.sub(r"(\\textbf\{)(.*?)(\})", "\\2", final_answer)
    final_answer = re.sub(r"(\\overline\{)(.*?)(\})", "\\2", final_answer)
    final_answer = re.sub(r"(\\boxed\{)(.*)(\})", "\\2", final_answer)

    # Normalize shorthand TeX:
    #  \fracab -> \frac{a}{b}
    #  \frac{abc}{bef} -> \frac{abc}{bef}
    #  \fracabc -> \frac{a}{b}c
    #  \sqrta -> \sqrt{a}
    #  \sqrtab -> sqrt{a}b
    final_answer = re.sub(r"(frac)([^{])(.)", "frac{\\2}{\\3}", final_answer)
    final_answer = re.sub(r"(sqrt)([^{])", "sqrt{\\2}", final_answer)
    final_answer = final_answer.replace("$", "")

    # Normalize 100,000 -> 100000
    if final_answer.replace(",", "").isdigit():
        final_answer = final_answer.replace(",", "")

    return final_answer


# From here till fix_sqrt() is borrowed from:
# https://github.com/EleutherAI/lm-evaluation-harness/blob/master/lm_eval/tasks/hendrycks_math.py#L88
async def is_equiv(str1: str | None, str2: str | None) -> bool:
    if str1 is None and str2 is None:
        logger.debug("WARNING: Both None")
        return True
    if str1 is None or str2 is None:
        return False

    try:
        ss1 = await strip_string(str1)
        ss2 = await strip_string(str2)
        return ss1 == ss2
    except Exception:
        return str1 == str2


async def strip_string(string: str) -> str:
    # linebreaks
    string = string.replace("\n", "")

    # remove inverse spaces
    string = string.replace("\\!", "")

    # replace \\ with \
    string = string.replace("\\\\", "\\")

    # replace tfrac and dfrac with frac
    string = string.replace("tfrac", "frac")
    string = string.replace("dfrac", "frac")

    # remove \left and \right
    string = string.replace("\\left", "")
    string = string.replace("\\right", "")

    # Remove circ (degrees)
    string = string.replace("^{\\circ}", "")
    string = string.replace("^\\circ", "")

    # remove dollar signs
    string = string.replace("\\$", "")

    # remove units (on the right)
    string = await remove_right_units(string)

    # remove percentage
    string = string.replace("\\%", "")
    # /% isn't a valid escape sequence, so this is just being treated as '%'
    string = string.replace("%", "")

    # " 0." equivalent to " ." and "{0." equivalent to "{." Alternatively, add "0" if "." is the start of the string
    string = string.replace(" .", " 0.")
    string = string.replace("{.", "{0.")
    # if empty, return empty string
    if len(string) == 0:
        return string
    if string[0] == ".":
        string = "0" + string

    # to consider: get rid of e.g. "k = " or "q = " at beginning
    if len(string.split("=")) == 2:
        if len(string.split("=")[0]) <= 2:
            string = string.split("=")[1]

    # fix sqrt3 --> sqrt{3}
    string = await fix_sqrt(string)

    # remove spaces
    string = string.replace(" ", "")

    # \frac1b or \frac12 --> \frac{1}{b} and \frac{1}{2}, etc. Even works with \frac1{72} (but not \frac{72}1). Also does a/b --> \\frac{a}{b}
    string = await fix_fracs(string)

    # manually change 0.5 --> \frac{1}{2}
    if string == "0.5":
        string = "\\frac{1}{2}"

    # NOTE: X/Y changed to \frac{X}{Y} in dataset, but in simple cases fix in case the model output is X/Y
    string = await fix_a_slash_b(string)

    return string


async def fix_fracs(string: str) -> str:
    substrs = string.split("\\frac")
    new_str = substrs[0]
    if len(substrs) > 1:
        substrs = substrs[1:]
        for substr in substrs:
            new_str += "\\frac"
            if substr[0] == "{":
                new_str += substr
            else:
                try:
                    assert len(substr) >= 2
                except AssertionError:
                    return string
                a = substr[0]
                b = substr[1]
                if b != "{":
                    if len(substr) > 2:
                        post_substr = substr[2:]
                        new_str += "{" + a + "}{" + b + "}" + post_substr
                    else:
                        new_str += "{" + a + "}{" + b + "}"
                else:
                    if len(substr) > 2:
                        post_substr = substr[2:]
                        new_str += "{" + a + "}" + b + post_substr
                    else:
                        new_str += "{" + a + "}" + b
    string = new_str
    return string


async def fix_a_slash_b(string: str) -> str:
    if len(string.split("/")) != 2:
        return string
    a = string.split("/")[0]
    b = string.split("/")[1]
    try:
        a_int = int(a)
        b_int = int(b)
        assert string == "{}/{}".format(a_int, b_int)
        new_string = "\\frac{" + str(a_int) + "}{" + str(b_int) + "}"
        return new_string
    except AssertionError:
        return string


async def remove_right_units(string: str) -> str:
    # "\\text{ " only ever occurs (at least in the val set) when describing units
    if "\\text{ " in string:
        splits = string.split("\\text{ ")
        assert len(splits) == 2
        return splits[0]
    else:
        return string


async def fix_sqrt(string: str) -> str:
    if "\\sqrt" not in string:
        return string
    splits = string.split("\\sqrt")
    new_string = splits[0]
    for split in splits[1:]:
        if split[0] != "{":
            a = split[0]
            new_substr = "\\sqrt{" + a + "}" + split[1:]
        else:
            new_substr = "\\sqrt" + split
        new_string += new_substr
    return new_string


# Both remove_boxed() and last_boxed_only_string() functions borrowed from:
# https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/hendrycks_math/utils.py#L53C1-L94C18
def remove_boxed(s: str) -> str:
    if "\\boxed " in s:
        left = "\\boxed "
        assert s[: len(left)] == left
        return s[len(left) :]

    left = "\\boxed{"

    assert s[: len(left)] == left
    assert s[-1] == "}"

    return s[len(left) : -1]


def last_boxed_only_string(string: str) -> str | None:
    idx = string.rfind("\\boxed")
    if "\\boxed " in string:
        return "\\boxed " + string.split("\\boxed ")[-1].split("$")[0]
    if idx < 0:
        idx = string.rfind("\\fbox")
        if idx < 0:
            return None

    i = idx
    right_brace_idx = None
    num_left_braces_open = 0
    while i < len(string):
        if string[i] == "{":
            num_left_braces_open += 1
        if string[i] == "}":
            num_left_braces_open -= 1
            if num_left_braces_open == 0:
                right_brace_idx = i
                break
        i += 1

    if right_brace_idx is None:
        retval = None
    else:
        retval = string[idx : right_brace_idx + 1]

    return retval


EQUIVALANCE_TEMPLATE = r"""
Look at the following two expressions (answers to a math problem) and judge whether they are equivalent. Only perform trivial simplifications

Examples:

  Expression 1: $2x+3$
  Expression 2: $3+2x$

Yes

  Expression 1: 3/2
  Expression 2: 1.5

Yes

  Expression 1: $x^2+2x+1$
  Expression 2: $y^2+2y+1$

No

  Expression 1: $x^2+2x+1$
  Expression 2: $(x+1)^2$

Yes

  Expression 1: 3245/5
  Expression 2: 649

No
(these are actually equal, don't mark them equivalent if you need to
do nontrivial simplifications)

  Expression 1: 2/(-3)
  Expression 2: -2/3

Yes
(trivial simplifications are allowed)

  Expression 1: 72 degrees
  Expression 2: 72

Yes
(give benefit of the doubt to units)

  Expression 1: 64
  Expression 2: 64 square feet

Yes
(give benefit of the doubt to units)

---

YOUR TASK


Respond with only "Yes" or "No" (without quotes). Do not include a rationale.

  Expression 1: %(expression1)s
  Expression 2: %(expression2)s
""".strip()


SUBSTITUTIONS = [
    ("an ", ""),
    ("a ", ""),
    (".$", "$"),
    ("\\$", ""),
    (r"\ ", ""),
    (" ", ""),
    ("mbox", "text"),
    (",\\text{and}", ","),
    ("\\text{and}", ","),
    ("\\text{m}", "\\text{}"),
]
REMOVED_EXPRESSIONS = [
    "square",
    "ways",
    "integers",
    "dollars",
    "mph",
    "inches",
    "ft",
    "hours",
    "km",
    "units",
    "\\ldots",
    "sue",
    "points",
    "feet",
    "minutes",
    "digits",
    "cents",
    "degrees",
    "cm",
    "gm",
    "pounds",
    "meters",
    "meals",
    "edges",
    "students",
    "childrentickets",
    "multiples",
    "\\text{s}",
    "\\text{.}",
    "\\text{\ns}",
    "\\text{}^2",
    "\\text{}^3",
    "\\text{\n}",
    "\\text{}",
    r"\mathrm{th}",
    r"^\circ",
    r"^{\circ}",
    r"\;",
    r",\!",
    "{,}",
    '"',
    "\\dots",
]
