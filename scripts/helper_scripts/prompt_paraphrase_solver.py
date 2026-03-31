r"""CLI solver: paraphrase the task prompt, then run default ``generate()``.

Requires local ``inspect_ai`` with ``apply_prompt_paraphrase`` (use ``uv run --with . ...``).

Example::

    uv run --with . --with inspect-evals --with openai inspect eval inspect_evals/gpqa_diamond \\
        --solver scripts/helper_scripts/prompt_paraphrase_solver.py@paraphrased_generate \\
        -S model=openai/gpt-4o-mini -S temperature=0.7 --log-dir logs/paraphrase
"""

from __future__ import annotations

from inspect_ai.model import Model
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    apply_prompt_paraphrase,
    multiple_choice,
    solver,
)


@solver
def paraphrased_generate(
    model: str | Model | None = None,
    instruction: str | None = None,
    choice_template: str | None = None,
    multiple_correct: bool = False,
    max_tokens: int | None = None,
    temperature: float = 0.7,
    paraphrase_max_tokens: int | None = 2048,
) -> Solver:
    """Paraphrase prompt with a separate model, then run task generation.

    For multiple-choice tasks (non-empty ``state.choices``), this calls
    ``multiple_choice()`` so answer parsing and scorer integration work.
    """
    paraphrase = apply_prompt_paraphrase(
        model=model,
        instruction=instruction,
        choice_template=choice_template,
        temperature=temperature,
        max_tokens=paraphrase_max_tokens,
    )
    choice_solver = multiple_choice(
        template=choice_template,
        multiple_correct=multiple_correct,
        max_tokens=max_tokens,
    )

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await paraphrase(state, generate)
        if state.completed:
            return state
        if state.choices:
            return await choice_solver(state, generate)
        return await generate(state)

    return solve
