"""Mathematical expression scorer using Math-Verify library."""

from typing import Literal

from inspect_ai._util.error import pip_dependency_error
from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target


def _latex(text: str) -> str:
    return text if text.startswith("$") else f"${text}$"


def _parse_config(math_verify, extraction_targets: list[Literal["latex", "expr"]]):
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
        extraction_targets: List of extraction targets to use. Defaults to ["latex", "expr"]. Having both will result in the parser giving higher priority to the latex extraction.
                            "latex" extracts LaTeX expressions with configurable options (see docstring) (e.g. r"$[ \sqrt{2} ]$"). Do note that the latex must be placed in latex environment to be parsable.
                            "expr" extracts plain mathematical expressions (e.g. r"1/2")
    """
    try:
        import math_verify
    except ImportError:
        raise pip_dependency_error("Math Scorer", ["math-verify[antlr4_13_2]>=0.9.0"])

    config = _parse_config(math_verify, extraction_targets)

    async def score(state: TaskState, target: Target) -> Score:
        result = math_verify.parse(state.output.completion, extraction_config=config)
        target_exprs = math_verify.parse(_latex(target.text), extraction_config=config)

        if not result:
            return Score(
                value=INCORRECT,
                explanation="Could not extract or parse mathematical answer from output",
            )
        if not target_exprs:
            return Score(
                value=INCORRECT,
                explanation="Could not extract or parse mathematical target from target",
            )

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
            answer=str(result[0]),
            explanation=state.output.completion,
        )

    return score
