from inspect_ai.solver._multiple_choice import (
    answer_character,
    answer_index,
    answer_options,
    unshuffle_choices,
)
from inspect_ai.solver._task_state import Choices, TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, stderr
from ._scorer import Scorer, scorer
from ._target import Target


def _choices_are_shuffled(choices: Choices) -> bool:
    return any(i != choice.original_position for i, choice in enumerate(choices))


def _score_target(target: Target, choices: Choices) -> tuple[list[int], list[str]]:
    target_positions = [
        answer_index(target_character) for target_character in target.text
    ]

    choice_positions = [i for i, choice in enumerate(choices) if choice.correct is True]

    answers = [answer_character(choice) for choice in choice_positions]

    return target_positions, answers


def _shuffled_explanation(choices: Choices) -> str:
    generated_answers = [
        answer_character(i)
        for i, choice in enumerate(choices)
        if choice.correct is True
    ]

    return f"Choices were shuffled before generating a response, the following was sent to the model:\n\n{answer_options(choices)}\nShuffled answer:\nANSWER: {', '.join(generated_answers)}"


@scorer(metrics=[accuracy(), stderr()])
def choice() -> Scorer:
    """
    Scorer for multiple choice answers, required by the `multiple_choice` solver.

    This assumes that the model was called using a template ordered with letters
    corresponding to the answers, so something like:

        What is the capital of France?

        A) Paris
        B) Berlin
        C) London

    The target for the dataset will then have a letter corresponding to the
    correct answer, e.g. the `Target` would be `"A"` for the above question. If
    multiple choices are correct, the `Target` can be an array of these letters.
    """

    async def score(state: TaskState, target: Target) -> Score:
        choices = state.choices

        if _choices_are_shuffled(choices):
            explanation = _shuffled_explanation(choices)
            # Unshuffle the choices so that we can score them correctly against
            # the target
            choices = unshuffle_choices(choices)
        else:
            explanation = state.output.completion

        target_positions, answers = _score_target(target, choices)

        generated_selected_choices = [
            i for i, choice in enumerate(choices) if choice.correct is True
        ]

        target_matches_choices = generated_selected_choices == sorted(target_positions)

        return Score(
            value=CORRECT if target_matches_choices else INCORRECT,
            answer=", ".join(answers),
            explanation=explanation,
        )

    return score
