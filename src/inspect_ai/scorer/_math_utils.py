"""Math utilities with optional Math-Verify support."""

from typing import Any


def compare_answers(
    answer: Any,
    target: Any,
    tolerance: float = 1e-8,
    allow_symbolic: bool = True,
    allow_numerical: bool = True,
) -> bool:
    """
    Compare two mathematical expressions for equivalence.

    Uses Math-Verify's intelligent comparison that handles:
    - Symbolic equivalence
    - Numerical equivalence within tolerance
    - Sets and intervals
    - Matrices
    - Inequalities

    Args:
        answer: Parsed answer expression
        target: Parsed target expression
        tolerance: Numerical tolerance for floating point comparison
        allow_symbolic: Whether to allow symbolic comparison
        allow_numerical: Whether to allow numerical comparison

    Returns:
        True if expressions are equivalent, False otherwise
    """
    from math_verify import verify  # type: ignore

    if answer is None or target is None:
        return False

    try:
        # Math-Verify's verify function handles all comparison logic
        # Note: Order matters! verify(gold, answer) is not symmetric

        # Convert tolerance (e.g., 1e-8) to rounding digits
        # tolerance = 1e-8 means 8 decimal places
        import math as math_module

        float_rounding = (
            max(1, int(-math_module.log10(tolerance))) if tolerance > 0 else 6
        )

        result = verify(
            target,  # gold answer
            answer,  # model answer
            float_rounding=float_rounding,
            # Math-Verify automatically handles symbolic and numerical comparison
            # The allow_symbolic and allow_numerical parameters are for backwards
            # compatibility but Math-Verify doesn't separate these concerns
        )
        return bool(result)
    except Exception:
        return False
