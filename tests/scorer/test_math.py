"""Tests for math scorer with Math-Verify integration."""

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, INCORRECT, Target, math


@pytest.mark.anyio
async def test_boxed_simple_number():
    scorer = math()
    state = simple_task_state(model_output="The answer is \\boxed{42}")
    result = await scorer(state, Target(["42"]))

    assert result.value == CORRECT
    assert result.answer == "42"


@pytest.mark.anyio
async def test_boxed_fraction():
    scorer = math()
    state = simple_task_state(model_output="\\boxed{\\frac{1}{2}}")
    result = await scorer(state, Target(["0.5"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_boxed_no_match():
    scorer = math()
    state = simple_task_state(model_output="\\boxed{42}")
    result = await scorer(state, Target(["43"]))

    assert result.value == INCORRECT
    assert result.answer == "42"


@pytest.mark.anyio
async def test_no_boxed():
    scorer = math()
    state = simple_task_state(model_output="The answer is 42")
    result = await scorer(state, Target(["42"]))

    # Math-Verify can extract plain numbers without \boxed{}
    assert result.value == CORRECT


@pytest.mark.anyio
async def test_multiple_boxed_as_set():
    """Test that multiple boxed answers are treated as a set by Math-Verify."""
    scorer = math()
    # Math-Verify treats multiple boxed answers as a set {10, 42}
    # This behavior differs from the old implementation which used the last one
    state = simple_task_state(model_output="\\boxed{10} and \\boxed{42}")
    result = await scorer(state, Target(["$\\{10, 42\\}$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_symbolic_equivalence():
    """Test symbolic equivalence - both answers should be in consistent format."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{2*x}")
    # Math-Verify requires target to be parseable too
    result = await scorer(state, Target(["$2*x$", "$x*2$"]))  # Provide both forms

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_numerical_tolerance():
    scorer = math(tolerance=1e-2)
    state = simple_task_state(model_output="\\boxed{0.333}")
    result = await scorer(state, Target(["0.33"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_boxed_without_backslash():
    """Test boxed without backslash - Math-Verify requires LaTeX environments."""
    scorer = math()
    # Math-Verify requires answers to be in LaTeX environments
    # Plain "boxed{42}" without \ won't be extracted
    state = simple_task_state(model_output="The answer is $42$")
    result = await scorer(state, Target(["42"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_malformed_latex_sqrt():
    """Test malformed sqrt - Math-Verify fixes this automatically."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{360\\sqrt{2}}")
    # Target should be in parseable format
    result = await scorer(state, Target(["$360\\sqrt{2}$"]))

    assert result.value == CORRECT


# New test cases for Math-Verify features


@pytest.mark.anyio
async def test_sqrt_without_braces():
    r"""Test \\sqrt2 is correctly parsed by Math-Verify."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{\\sqrt2}")
    # Target must be in LaTeX format for Math-Verify
    result = await scorer(state, Target(["$\\sqrt{2}$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_sqrt_with_braces():
    r"""Test \\sqrt{2} is correctly parsed."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{\\sqrt{2}}")
    result = await scorer(state, Target(["$\\sqrt{2}$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_percentage_to_decimal():
    """Test percentage handling by Math-Verify (50% -> 0.5)."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{50\\%}")
    # Math-Verify converts 50% to 0.5
    result = await scorer(state, Target(["0.5"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_percentage_decimal_value():
    """Test 33.5% is parsed as 0.335."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{33.5\\%}")
    result = await scorer(state, Target(["0.335"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_multiple_extraction_formats_dollar_dollar():
    """Test Math-Verify's $$...$$ format extraction."""
    scorer = math()
    state = simple_task_state(model_output="The answer is $$42$$")
    result = await scorer(state, Target(["42"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_multiple_extraction_formats_single_dollar():
    """Test Math-Verify's $...$ format extraction."""
    scorer = math()
    state = simple_task_state(model_output="The answer is $42$")
    result = await scorer(state, Target(["42"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_complex_latex_fraction():
    """Test complex LaTeX fraction handled by Math-Verify."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{\\frac{1}{2}}")
    result = await scorer(state, Target(["0.5"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_sqrt_with_fraction():
    """Test sqrt with fraction inside."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{\\sqrt{\\frac{1}{4}}}")
    result = await scorer(state, Target(["0.5"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_nested_sqrt():
    """Test nested sqrt: sqrt(sqrt(2))."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{\\sqrt{\\sqrt{2}}}")
    result = await scorer(state, Target(["2**(1/4)"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_set_notation():
    """Test Math-Verify's set operation support."""
    scorer = math()
    state = simple_task_state(model_output="$\\{1,2,3\\}$")
    # Target must also be in LaTeX format
    result = await scorer(state, Target(["$\\{1, 2, 3\\}$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_interval_notation():
    """Test interval notation."""
    scorer = math()
    # Tuples/intervals need LaTeX format
    state = simple_task_state(model_output="$\\left(1, 2\\right)$")
    result = await scorer(state, Target(["$\\left(1, 2\\right)$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_scientific_notation():
    """Test scientific notation."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{1.5 \\times 10^3}")
    result = await scorer(state, Target(["1500"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_pi_symbol():
    """Test pi symbol handling."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{2\\pi}")
    # Target needs LaTeX format with pi
    result = await scorer(state, Target(["$2\\pi$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_multiple_operations():
    """Test multiple operations in expression."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{(1 + 2) \\times 3}")
    result = await scorer(state, Target(["9"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_algebraic_simplification():
    """Test algebraic simplification."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{x^2 - x^2}")
    result = await scorer(state, Target(["0"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_invalid_expression():
    """Test that invalid expressions are handled gracefully."""
    scorer = math()
    state = simple_task_state(model_output="\\boxed{not a number}")
    result = await scorer(state, Target(["42"]))

    assert result.value == INCORRECT


@pytest.mark.anyio
async def test_plain_symbolic_answer_with_latex_target():
    """Test plain symbolic answer (e.g., '-1 + sqrt(3)') matches LaTeX target."""
    scorer = math()
    # Target in LaTeX format without delimiters
    state = simple_task_state(model_output="-1 + sqrt(3)")
    result = await scorer(state, Target([r"\sqrt{3} - 1"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_plain_symbolic_answer_with_fraction():
    """Test plain symbolic answer with fraction matches LaTeX target."""
    scorer = math()
    state = simple_task_state(model_output="(3*sqrt(5))/7")
    result = await scorer(state, Target([r"\frac{3\sqrt{5}}{7}"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_commutative_operations():
    """Test that commutative operations are recognized as equivalent."""
    scorer = math()
    # Use $...$ format for symbolic expressions
    state = simple_task_state(model_output="$x + 2$")
    result = await scorer(state, Target(["$2 + x$"]))

    assert result.value == CORRECT


@pytest.mark.anyio
async def test_symbolic_with_functions():
    """Test symbolic expressions with math functions."""
    scorer = math()
    state = simple_task_state(model_output="sqrt(2) + sqrt(2)")
    result = await scorer(state, Target(["$2\\sqrt{2}$"]))

    assert result.value == CORRECT
