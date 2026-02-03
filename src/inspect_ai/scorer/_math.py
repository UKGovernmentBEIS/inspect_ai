"""Mathematical expression scorer using Math-Verify library."""

from typing import TYPE_CHECKING, Any, Literal

from inspect_ai._util.error import pip_dependency_error
from inspect_ai.solver._task_state import TaskState

try:
    from sympy import SympifyError, sympify
except ImportError:
    sympify = None  # type: ignore
    SympifyError = Exception  # type: ignore

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target

if TYPE_CHECKING:
    pass


def _latex(text: str) -> str:
    return text if text.startswith("$") else f"${text}$"


def _try_sympify(text: str) -> list[Any]:
    """Try to parse text as a mathematical expression using sympy.

    Returns a list containing the parsed sympy expression, or empty list on failure.
    """
    if sympify is None:
        return []

    try:
        # Strip whitespace and try to parse
        expr = sympify(text.strip())
        return [expr]
    except (SympifyError, Exception):
        return []


def _parse_config(
    math_verify: Any, extraction_targets: list[Literal["latex", "expr"]]
) -> list[Any]:
    return (
        [
            math_verify.LatexExtractionConfig()
            if "latex" in extraction_targets
            else None,
            math_verify.ExprExtractionConfig()
            if "expr" in extraction_targets
            else None,
        ]
        if any(extraction_targets)
        else []
    )


@scorer(metrics=[accuracy(), stderr()])
def math(
    extraction_targets: list[Literal["latex", "expr"]] = ["latex", "expr"],
) -> Scorer:
    r"""Scorer for mathematical expressions.

    Args:
        extraction_targets: List of extraction targets to use. Defaults to ["latex", "expr"].
                            Having both will result in the parser giving higher priority to the latex extraction.
                            "latex" extracts LaTeX expressions (e.g. r"$\sqrt{2}$"). LaTeX must be in an environment to be parsable.
                            "expr" extracts plain mathematical expressions (e.g. r"1/2")

    If extraction fails, the scorer will attempt to parse the output/target as a plain mathematical
    expression using sympy. This allows matching plain expressions like "sqrt(2) + sqrt(2)" against "2*sqrt(2)".
    """
    try:
        import math_verify
    except ImportError:
        raise pip_dependency_error("Math Scorer", ["math-verify[antlr4_13_2]>=0.9.0"])

    config = _parse_config(math_verify, extraction_targets)

    async def score(state: TaskState, target: Target) -> Score:
        result = math_verify.parse(state.output.completion, extraction_config=config)

        # Fallback: also try parsing as plain mathematical expression with sympy
        # This handles cases where math_verify might extract only part of an expression
        # (e.g., "-1" from "-1 + sqrt(3)") or miss plain syntax entirely
        if not result:
            result = _try_sympify(state.output.completion)
        else:
            # Also try sympy to see if it parses the whole expression differently
            sympy_result = _try_sympify(state.output.completion)
            if sympy_result and sympy_result[0] not in result:
                result.extend(sympy_result)

        if not result:
            return Score(
                value=INCORRECT,
                explanation="Could not extract or parse mathematical answer from output",
            )

        # Iterate over each target possibility
        for target_text in target:
            target_exprs = math_verify.parse(
                _latex(target_text), extraction_config=config
            )

            # Fallback: try parsing as plain mathematical expression with sympy
            if not target_exprs:
                target_exprs = _try_sympify(target_text)

            if not target_exprs:
                continue  # Try next target if this one can't be parsed

            for target_expr in target_exprs:
                for answer_expr in result:
                    try:
                        if math_verify.verify(target_expr, answer_expr):
                            return Score(
                                value=CORRECT,
                                answer=str(answer_expr),
                                explanation=state.output.completion,
                            )
                    except Exception:
                        continue

        return Score(
            value=INCORRECT,
            answer=str(result[0]) if result else "None",
            explanation=state.output.completion,
        )

    return score
