import pytest
from inspect_ai.model._model import ModelName
from inspect_ai.scorer import Target, Score
from inspect_ai.scorer._metric import CORRECT, INCORRECT
from inspect_ai.solver import TaskState
from inspect_ai.dataset import Sample
from f1 import f1_scorer, normalize_answer


# Helper function to create a TaskState
def create_task_state(completion: str) -> TaskState:
    return TaskState(
        model=ModelName("openai/gpt-4o-mini"),
        sample_id="test_id",
        epoch=0,
        input=Sample(input="test input"),
        messages=[],
        output=type("obj", (object,), {"completion": completion})(),
    )


@pytest.mark.asyncio
async def test_perfect_match():
    scorer = f1_scorer()
    state = create_task_state("The cat sat on the mat.")
    target = Target(["The cat sat on the mat.", "banana"])
    score = await scorer(state, target)
    assert score.value == pytest.approx(1.0)
    assert score.answer == "The cat sat on the mat."


@pytest.mark.asyncio
async def test_partial_match():
    scorer = f1_scorer()
    state = create_task_state("A cat sat on a mat.")
    target = Target(["The cat sat on the television."])
    score = await scorer(state, target)
    assert 0 < score.value < 1, f"score value: {score.value}"
    assert score.answer == "A cat sat on a mat.", f"score answer: {score.answer}"


@pytest.mark.asyncio
async def test_no_match():
    scorer = f1_scorer()
    state = create_task_state("The dog slept on the floor.")
    target = Target(["The cat sat on the mat."])
    score = await scorer(state, target)
    assert score.value == pytest.approx(0.0)
    assert score.answer == "The dog slept on the floor."


@pytest.mark.asyncio
async def test_cannotanswer_correct():
    scorer = f1_scorer()
    state = create_task_state("CANNOTANSWER")
    target = Target(["CANNOTANSWER"])
    score = await scorer(state, target)
    assert score.value == CORRECT, f"score value: {score.value}"
    assert score.answer == "CANNOTANSWER", f"score answer: {score.answer}"


@pytest.mark.asyncio
async def test_cannotanswer_incorrect():
    scorer = f1_scorer()
    state = create_task_state("CANNOTANSWER")
    target = Target(["The cat sat on the mat."])
    score = await scorer(state, target)
    assert score.value == INCORRECT, f"score value: {score.value}"
    assert score.answer == "CANNOTANSWER", f"score answer: {score.answer}"


@pytest.mark.asyncio
async def test_multiple_references():
    scorer = f1_scorer()
    state = create_task_state("A feline rested on the carpet.")
    target = Target(
        [
            "The cat sat on the mat.",
            "A feline rested on the rug.",
            "The kitten lounged on the carpet.",
        ]
    )
    score = await scorer(state, target)
    assert 0 < score.value < 1, f"score value: {score.value}"
    assert (
        score.answer == "A feline rested on the carpet."
    ), f"score answer: {score.answer}"


@pytest.mark.asyncio
async def test_empty_prediction():
    scorer = f1_scorer()
    state = create_task_state("")
    target = Target(["The cat sat on the mat."])
    score = await scorer(state, target)
    assert score.value == pytest.approx(0.0)
    assert score.answer == ""


@pytest.mark.asyncio
async def test_empty_target():
    scorer = f1_scorer()
    state = create_task_state("The cat sat on the mat.")
    target = Target([""])
    score = await scorer(state, target)
    assert score.value == pytest.approx(0.0)
    assert score.answer == "The cat sat on the mat."
