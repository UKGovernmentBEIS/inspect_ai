from random import Random

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, INCORRECT, Target, choice


@pytest.mark.asyncio
async def test_score_single_letter():
    scorer = choice()
    state = simple_task_state(
        model_output="ANSWER: A",
        choices=["choice 1", "choice 2"],
    )
    state.choices.mark_choice(0, True)
    state.choices.mark_choice(1, False)

    result = await scorer(state, Target("A"))
    assert result.text == CORRECT
    assert result.answer == "A"
    assert result.explanation == "ANSWER: A"


@pytest.mark.asyncio
async def test_score_multiple_letters():
    scorer = choice()
    state = simple_task_state(
        model_output="ANSWER: A, B",
        choices=["choice 1", "choice 2"],
    )
    state.choices.mark_choice(0, True)
    state.choices.mark_choice(1, True)

    result = await scorer(state, Target(["A", "B"]))
    assert result.text == CORRECT
    assert result.answer == "A, B"
    assert result.explanation == "ANSWER: A, B"


@pytest.mark.asyncio
async def test_letter_incorrect_if_false_positives_found():
    scorer = choice()
    state = simple_task_state(
        model_output="ANSWER: A, B",
        choices=["choice 1", "choice 2"],
    )
    state.choices.mark_choice(0, True)
    state.choices.mark_choice(1, True)

    # Model generated B as an answer but not valid
    result = await scorer(state, Target("A"))
    assert result.text == INCORRECT
    assert result.answer == "A, B"
    assert result.explanation == "ANSWER: A, B"


@pytest.mark.asyncio
async def test_letter_incorrect_if_missed_correct_answers():
    scorer = choice()
    state = simple_task_state(
        model_output="ANSWER: A",
        choices=["choice 1", "choice 2"],
    )
    state.choices.mark_choice(0, True)
    state.choices.mark_choice(1, False)

    # Model generated B as an answer but not valid
    result = await scorer(state, Target(["A", "B"]))
    assert result.text == INCORRECT
    assert result.answer == "A"
    assert result.explanation == "ANSWER: A"


@pytest.mark.asyncio
async def test_score_shuffled_positions_letter():
    scorer = choice()
    state = simple_task_state(
        # "A" is the correct answer ("choice 3") as far as the model is concerned
        model_output="ANSWER: A",
        # Choices initially in order from Sample, Target below says "choice 3"
        # is correct
        choices=["choice 1", "choice 2", "choice 3"],
    )
    state.choices.shuffle(Random(4))
    state.choices.mark_choice(0, True)  # choice 3 because of shuffling
    state.choices.mark_choice(1, False)  # choice 2 because of shuffling
    state.choices.mark_choice(2, False)  # choice 1 because of shuffling

    # The target is based on unshuffled choices, choice corresponding to
    # "choice 3" is correct
    result = await scorer(state, Target(["C"]))
    assert result.text == CORRECT
    assert result.answer == "C"
    assert (
        result.explanation
        == "Choices were shuffled before generating a response, the following was sent to the model:\n\nA) choice 3\nB) choice 2\nC) choice 1\nShuffled answer:\nANSWER: A"
    )


@pytest.mark.asyncio
async def test_correct_single_answer():
    scorer = choice()
    state = simple_task_state(model_output="ANSWERS: A", choices=["A"])
    state.choices.mark_choice(0, True)
    result = await scorer(state, Target(["A"]))

    assert result.text == CORRECT
    assert result.answer == "A"
    assert result.explanation == "ANSWERS: A"


@pytest.mark.asyncio
async def test_correct_multiple_answers_one_incorrect():
    scorer = choice()
    state = simple_task_state(model_output="ANSWERS: ", choices=["A"])
    state.choices.mark_choice(0, False)
    result = await scorer(state, Target([""]))

    assert result.text == CORRECT
    assert result.answer == ""
    assert result.explanation == "ANSWERS: "


@pytest.mark.asyncio
async def test_correct_multiple_answers_all_incorrect():
    scorer = choice()
    state = simple_task_state(model_output="ANSWERS: ", choices=["A", "B"])
    state.choices.mark_choice(0, False)
    state.choices.mark_choice(1, False)
    result = await scorer(state, Target(""))

    assert result.text == CORRECT
    assert result.answer == ""
    assert result.explanation == "ANSWERS: "
