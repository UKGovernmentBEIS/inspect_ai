"""Tests for math scorer with Math-Verify integration."""

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, Target, math
from inspect_ai.scorer._math import (
    extract_last_integer,
    find_last_boxed_content,
    normalize_string,
    remove_inner_boxed,
    remove_invalid_characters,
    remove_outer_brackets,
    strip,
)


@pytest.mark.parametrize(
    "output,target,expected",
    [
        ("The answer is \\boxed{42}", "42", CORRECT),
        ("\\boxed{\\frac{1}{2}}", "0.5", CORRECT),
        ("\\boxed{\\sqrt{2}}", "3", INCORRECT),
    ],
)
async def test_boxed(output, target, expected):
    scorer = math()
    state = simple_task_state(model_output=output)
    result = await scorer(state, Target([target]))

    assert result.value == expected


@pytest.mark.parametrize(
    "output,target,expected",
    [
        ("\\boxed{\\sqrt{2}}", "$\\sqrt{2}$", CORRECT),  # sqrt with braces
        ("\\boxed{\\sqrt2}", "$\\sqrt{2}$", CORRECT),  # sqrt without braces
        ("\\boxed{sqrt(2)}", "$\\sqrt{2}$", CORRECT),  # sqrt with parentheses
    ],
)
async def test_sqrt(output, target, expected):
    scorer = math()
    state = simple_task_state(model_output=output)
    result = await scorer(state, Target([target]))

    assert result.value == expected


@pytest.mark.parametrize(
    "output,target,expected",
    [
        ("The answer is 42", "42", CORRECT),  # simple number
        ("$\\sqrt{2}$", "$\\sqrt{2}$", CORRECT),  # LaTeX expression
        ("1 + 0.5 = 1.5", "1.5", CORRECT),  # algebraic expression
        ("2*sqrt(2)", "2.8284271247461903", CORRECT),  # symbolic expression
        ("0.", "0", CORRECT),  # decimal
        ("1/5", "0.2", CORRECT),  # fraction
        ("33.5%", "0.335", CORRECT),  # percentage
        ("1.5 * 10^3", "1500", CORRECT),  # scientific notation
        ("2*(1 + 2) * 3", "18", CORRECT),  # multiple operations
        ("x^2 - x^2", "0", CORRECT),  # algebraic simplification
        ("not a number", "None", NOANSWER),  # invalid expression → parse fail
        ("sqrt(2) + sqrt(2)", "2.8284271247461903", CORRECT),  # symbolic expression
        ("2(1 + 2) * 3", "18", CORRECT),  # multiple operations
        (
            r"\boxed{\frac{6\sqrt{1789-240\sqrt{21}}+8\sqrt{1236-240\sqrt{21}}}{5}}.",
            r"96-10\sqrt{21}",
            CORRECT,
        ),
        (
            "For 73/4, m = 73 and n = 4 so that m + n = 73 + 4 = 77.\n\nThus, the final answer is: boxed {77}.",
            "77",
            CORRECT,
        ),
        (
            "The final answer is therefore □{610}.",
            "610",
            CORRECT,
        ),
        (
            "Thus, the final answer is: boxed {19}.",
            "19",
            CORRECT,
        ),
        (
            "\boxed{6\\sqrt{3} + 5\\pi}",
            r"5\pi + 6\sqrt{3}",
            CORRECT,
        ),
    ],
)
async def test_no_boxed(output, target, expected):
    scorer = math()
    state = simple_task_state(model_output=output)

    result = await scorer(state, Target([target]))
    assert result.value == expected


@pytest.mark.parametrize(
    "output,target,expected",
    [
        ("{1, 2}", "{1, 2}", CORRECT),
        ("{2, 1}", "{1, 2}", CORRECT),  # order-insensitive
        ("{1, 2, 3}", "{1, 2}", INCORRECT),  # different cardinality
        ("{1, 3}", "{1, 2}", INCORRECT),  # different element
    ],
)
async def test_list_valued_answers(output, target, expected):
    # Brace-delimited sets parse to Python lists; identical sets must score
    # CORRECT rather than being unconditionally rejected.
    scorer = math()
    state = simple_task_state(model_output=output)
    result = await scorer(state, Target([target]))
    assert result.value == expected


@pytest.mark.parametrize("output", [r"\boxed{inf}", r"\boxed{Infinity}", "-inf"])
async def test_infinite_float_does_not_crash(output):
    # float("inf") must not crash the scorer with OverflowError from int(inf).
    # extract_answer returns None for these (no finite mathematical
    # expression to compare), so the parse-failure branch records NOANSWER.
    scorer = math()
    state = simple_task_state(model_output=output)
    result = await scorer(state, Target(["0"]))
    assert result.value == NOANSWER


# ============================================================================
# EXTRACTION FUNCTION TESTS
# ============================================================================


def test_find_last_boxed_content():
    """Test extraction of boxed content from text."""
    # Basic boxed content
    assert find_last_boxed_content(r"The answer is \boxed{42}") == "42"

    # Multiple boxed - should return last one
    assert find_last_boxed_content(r"\boxed{10} and \boxed{42}") == "42"

    # No boxed content
    assert find_last_boxed_content("No boxed content here") is None

    # Empty string
    assert find_last_boxed_content("") is None


def test_remove_inner_boxed():
    """Test removal of nested boxed expressions."""
    # Nested boxed
    assert remove_inner_boxed(r"\boxed{42}") == "42"

    # No boxed content
    assert remove_inner_boxed("plain text") == "plain text"


def test_extract_last_integer():
    """Test extraction of last integer from text."""
    # Single integer
    assert extract_last_integer("The answer is 42") == 42

    # Multiple integers - should return last one
    assert extract_last_integer("Results: 10, 20, 30") == 30

    # No integers
    assert extract_last_integer("No numbers here") is None

    # Empty string
    assert extract_last_integer("") is None


# ============================================================================
# NORMALIZATION FUNCTION TESTS
# ============================================================================


def test_strip():
    """Test stripping whitespace and LaTeX newlines."""
    # Basic whitespace
    assert strip("  42  ") == "42"

    # LaTeX newlines
    assert strip(r"\n42\n") == "42"

    # LaTeX spaces (string starts with \\ followed by space)
    assert strip("\\ 42") == "42"

    # Empty string
    assert strip("") == ""


def test_normalize_string():
    """Test LaTeX string normalization."""
    # Remove sizing commands and convert brackets (brackets become parens)
    assert normalize_string(r"\left[42\right]") == "(42)"

    # Extract value after equals
    assert normalize_string("x = 42") == "42"

    # Remove text environments
    assert normalize_string(r"\text{answer: }42") == "42"

    # Remove dollar signs
    assert normalize_string("$42$") == "42"


def test_remove_outer_brackets():
    """Test removal of outer parentheses."""
    # Single layer
    assert remove_outer_brackets("(42)") == "42"

    # Multiple layers
    assert remove_outer_brackets("((1+2))") == "1+2"

    # Non-matching (should not remove)
    assert remove_outer_brackets("(1)+(2)") == "(1)+(2)"

    # No brackets
    assert remove_outer_brackets("42") == "42"


def test_remove_invalid_characters():
    """Test removal of LaTeX spacing commands."""
    # Thin space
    assert remove_invalid_characters(r"1\,234") == "1234"

    # Medium space
    assert remove_invalid_characters(r"x\;=\;42") == "x=42"

    # Multiple spacing commands
    assert remove_invalid_characters(r"a\:b\!c") == "abc"


@pytest.mark.parametrize(
    "output",
    [
        pytest.param("I'm not sure how to solve this.", id="no_numeric_content"),
        pytest.param("The answer is somewhere around forty-two.", id="words_only"),
        pytest.param("", id="empty_completion"),
        pytest.param("Let me think... the result is = = = ", id="ambiguous_equals"),
    ],
)
async def test_parse_failure_yields_noanswer(output):
    """Return NOANSWER when extract_answer returns None.

    When the model's completion contains no parseable mathematical
    expression, record NOANSWER rather than INCORRECT. Same silent-failure
    family as #4026 (model_graded_qa / _fact), addressed for the
    model-graded scorers in #4048. Without this fix, a sample where the
    model gave no answer at all is silently counted as a wrong answer in
    aggregate metrics, conflating "no signal" with "scored 0".
    """
    scorer = math()
    state = simple_task_state(model_output=output)
    result = await scorer(state, Target(["42"]))

    assert result.value == NOANSWER, (
        f"expected NOANSWER when extract_answer returns None for "
        f"completion {output!r}, got {result.value!r}"
    )
    # The completion is preserved as the answer for downstream observability,
    # rather than the literal string "None" that the prior code emitted.
    assert result.answer == output


async def test_parse_success_with_wrong_value_yields_incorrect():
    """Parseable but wrong answer still gets INCORRECT.

    NOANSWER is reserved for the parse-failure case.
    """
    scorer = math()
    state = simple_task_state(model_output="The answer is \\boxed{5}")
    result = await scorer(state, Target(["42"]))

    assert result.value == INCORRECT
