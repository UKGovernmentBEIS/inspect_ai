"""Mathematical expression scorer using Math-Verify library."""

from inspect_ai._util.error import pip_dependency_error
from inspect_ai.solver._task_state import TaskState

from ._math_utils import compare_answers
from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target


@scorer(metrics=[accuracy(), stderr()])
def math(
    tolerance: float = 1e-8,
    allow_symbolic: bool = True,
    allow_numerical: bool = True,
) -> Scorer:
    r"""
    Scorer for mathematical expressions using Math-Verify library.

    **Requires optional dependency:**
    ```bash
    pip install inspect-ai[math]
    ```

    Or install math-verify directly:
    ```bash
    pip install "math-verify[antlr4_13_2]>=0.9.0"
    ```

    This scorer uses the Math-Verify library from HuggingFace, which provides
    robust extraction, parsing, and comparison of mathematical expressions.

    Features:
    - Automatic answer extraction from multiple formats:
      * \\boxed{answer} (prioritized)
      * $$answer$$
      * $answer$
      * Plain expressions

    - Advanced LaTeX parsing with automatic fixes:
      * Malformed operators: \\sqrt2 → \\sqrt{2}
      * Missing braces: \\frac12 → \\frac{1}{2}
      * Percentage conversion: 50% → 0.5
      * Unit handling: 10 cm → 10

    - Intelligent comparison:
      * Symbolic equivalence: 2*x equals x*2
      * Numerical equivalence within tolerance
      * Set and interval comparison
      * Matrix operations
      * Inequality handling

    Args:
        tolerance: Numerical tolerance for floating-point comparison (default: 1e-8)
        allow_symbolic: Allow symbolic comparison (default: True)
        allow_numerical: Allow numerical comparison (default: True)

    Returns:
        Scorer that evaluates mathematical expressions

    Examples:
        >>> from inspect_ai.scorer import math
        >>> scorer = math(tolerance=1e-6)

        # Works with various formats:
        # - "\\boxed{42}"
        # - "The answer is $$\\frac{1}{2}$$"
        # - "Result: $\\sqrt{2}$"
        # - "50%" (converted to 0.5)
    """
    try:
        import math_verify
    except ImportError:
        raise pip_dependency_error("Math Scorer", ["math-verify[antlr4_13_2]>=0.9.0"])

    async def score(state: TaskState, target: Target) -> Score:
        # Extract and parse the model's answer using Math-Verify
        text = state.output.completion

        result = math_verify.parse(
            text,
            extraction_config=[
                math_verify.LatexExtractionConfig(boxed_match_priority=0),
                math_verify.ExprExtractionConfig(),
            ],
        )

        if result is None:
            return Score(
                value=INCORRECT,
                explanation="Could not extract or parse mathematical answer from output",
            )

        # Try to match against any of the target answers
        target_exprs = math_verify.parse(
            target.text,
            extraction_config=[
                math_verify.LatexExtractionConfig(),
                math_verify.ExprExtractionConfig(),
            ],
        )

        if target_exprs is None:
            return Score(
                value=INCORRECT,
                explanation="Could not extract or parse mathematical target from target",
            )

        # Use Math-Verify's comparison
        for target_expr in target_exprs:
            for answer_expr in result:
                if compare_answers(
                    answer=answer_expr,
                    target=target_expr,
                    tolerance=tolerance,
                    allow_symbolic=allow_symbolic,
                    allow_numerical=allow_numerical,
                ):
                    return Score(
                        value=CORRECT,
                        answer=str(answer_expr),
                        explanation=state.output.completion,
                    )

        return Score(
            value=INCORRECT,
            answer=str(result),
            explanation=state.output.completion,
        )

    return score
