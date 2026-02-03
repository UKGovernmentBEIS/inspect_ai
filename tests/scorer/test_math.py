"""Tests for math scorer with Math-Verify integration."""

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, INCORRECT, Target, math


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
        # Should Work
        ("2(1 + 2) * 3", "18", INCORRECT),  # multiple operations
        ("Answer: sqrt(2)", "1.4142135623730951", INCORRECT),  # prepended answer
    ],
)
async def test_no_boxed(output, target, expected):
    scorer = math()
    state = simple_task_state(model_output=output)

    result = await scorer(state, Target([target]))
    assert result.value == expected


@pytest.mark.anyio
async def test_multiple_boxed_as_set():
    """Test that multiple boxed answers are treated as a set by Math-Verify."""
    scorer = math()
    # Math-Verify treats multiple boxed answers as a set {10, 42}
    # This behavior differs from the old implementation which used the last one
    state = simple_task_state(model_output="\\boxed{10} and \\boxed{42}")
    result = await scorer(state, Target(["$\\{10, 42\\}$"]))

    assert result.value == CORRECT
