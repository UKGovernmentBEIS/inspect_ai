from __future__ import annotations

from inspect_ai.model import ChatMessage, GenerateConfig, Model, ModelOutput, get_model
from inspect_ai.util import resource

from ._multiple_choice import SINGLE_ANSWER_TEMPLATE
from ._multiple_choice import prompt as format_multiple_choice_prompt
from ._solver import Generate, Solver, solver
from ._task_state import TaskState

DEFAULT_PROMPT_PARAPHRASE_TEMPLATE = """\
Paraphrase the following evaluation prompt for a robustness study.

Rules:
- Preserve the same meaning, constraints, and required answer format.
- Change wording and sentence structure only.
- Do not add new instructions or remove requirements.
- Reply with only the paraphrased prompt text (no preamble, no quotes).

Prompt to paraphrase:
{prompt}
"""


@solver
def apply_prompt_paraphrase(
    model: str | Model | None = None,
    instruction: str | None = None,
    choice_template: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = 2048,
) -> Solver:
    """Paraphrase the task prompt before it is shown to the eval model.

    Intended for **prompt robustness** (R_prompt): compare accuracy under the
    original prompt (baseline) to accuracy after semantically equivalent
    paraphrases.

    Args:
        model: Model used for paraphrasing. Must be provided and must differ
            from the active eval model.
        instruction: Prompt template for the paraphrase call. Must include
            ``{prompt}``, which is filled with the full user-facing task prompt.
            For multiple-choice samples (non-empty ``choices``), that text is
            formatted like the ``multiple_choice`` solver so options and line
            breaks are included. May be a path (passed to
            :func:`~inspect_ai.util.resource`).
        choice_template: When the sample has choices, template used to combine
            ``{question}``, ``{choices}``, and ``{letters}`` before paraphrasing
            (same contract as ``multiple_choice``). Defaults to the standard
            single-answer template; use a CoT or custom template string/path to
            match your task.
        temperature: Sampling temperature for the paraphrase generation.
        max_tokens: Cap for paraphrase completion (defaults to 2048).
    """
    templ = resource(instruction or DEFAULT_PROMPT_PARAPHRASE_TEMPLATE)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if model is None:
            raise ValueError(
                "apply_prompt_paraphrase requires a paraphrase model "
                "(e.g. -S model=openai/gpt-4o-mini)."
            )
        resolved = model if isinstance(model, Model) else get_model(model)
        if resolved.name == state.model.name:
            raise ValueError(
                "apply_prompt_paraphrase model must differ from eval model "
                f"('{state.model.name}')."
            )
        prompt_text = _eval_user_prompt_for_paraphrase(state, choice_template)
        user_prompt = templ.format(prompt=prompt_text)

        config = GenerateConfig(temperature=temperature, max_tokens=max_tokens)
        output: ModelOutput = await resolved.generate(
            user_prompt,
            tools=[],
            tool_choice=None,
            config=config,
        )
        paraphrased = (output.completion or "").strip()
        if not paraphrased:
            raise ValueError(
                "Paraphrase model returned empty text; check model and template."
            )

        _replace_input_prompt(state, paraphrased)
        _replace_last_user_content(state.messages, state.input_text)
        return state

    return solve


def _eval_user_prompt_for_paraphrase(
    state: TaskState, choice_template: str | None
) -> str:
    """Text actually shown to the model: raw user prompt or full MC formatting."""
    raw = state.user_prompt.text
    if not state.choices:
        return raw
    tmpl = resource(choice_template or SINGLE_ANSWER_TEMPLATE)
    return format_multiple_choice_prompt(
        question=raw,
        choices=state.choices,
        template=str(tmpl),
    )


def _replace_last_user_content(messages: list[ChatMessage], new_text: str) -> None:
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.role == "user":
            messages[idx] = msg.model_copy(update={"content": new_text})
            return
    raise ValueError(
        "apply_prompt_paraphrase requires at least one user message in state.messages."
    )


def _replace_input_prompt(state: TaskState, new_text: str) -> None:
    if isinstance(state.input, str):
        state._input = new_text
        return

    for idx in range(len(state.input) - 1, -1, -1):
        msg = state.input[idx]
        if msg.role == "user":
            updated_input = list(state.input)
            updated_input[idx] = msg.model_copy(update={"content": new_text})
            state._input = updated_input
            return

    raise ValueError(
        "apply_prompt_paraphrase requires at least one user message in state.input."
    )
