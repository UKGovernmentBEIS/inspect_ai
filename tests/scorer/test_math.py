"""Tests for math scorer with Math-Verify integration."""

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, INCORRECT, Target, math
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
        ("not a number", "None", INCORRECT),  # invalid expression
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
        (
            "\\boxed{\\frac{1+\\sqrt7}2}.",
            "\\frac{\\sqrt{7} + 1}{2}",
            CORRECT,
        ),
        # Should Work
        ("Answer: sqrt(2)", "1.4142135623730951", INCORRECT),  # prepended answer
    ],
)
async def test_no_boxed(output, target, expected):
    scorer = math()
    state = simple_task_state(model_output=output)

    result = await scorer(state, Target([target]))
    assert result.value == expected


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
