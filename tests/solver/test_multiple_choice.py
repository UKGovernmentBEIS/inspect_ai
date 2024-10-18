from random import Random

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput
from inspect_ai.scorer._choice import choice
from inspect_ai.scorer._metric import CORRECT
from inspect_ai.scorer._target import Target
from inspect_ai.solver import MultipleChoiceTemplate, TaskState, multiple_choice
from inspect_ai.solver._task_state import Choice


async def generate(state: TaskState) -> TaskState:
    state.messages.append(ChatMessageAssistant(content="ANSWER: A"))
    state.output = ModelOutput.from_content(model="model", content="ANSWER: A")
    return state


def generate_for_multiple_correct(answers: str):
    async def generate(state: TaskState) -> TaskState:
        state.messages.append(ChatMessageAssistant(content=answers))
        state.output = ModelOutput.from_content(model="model", content=answers)
        return state

    return generate


@pytest.mark.asyncio
async def test_raises_exception_if_no_choices():
    solver = multiple_choice()
    state = simple_task_state()
    with pytest.raises(
        ValueError, match="The multiple_choice solver requires samples with choices"
    ):
        await solver(state=state, generate=generate)


@pytest.mark.asyncio
async def test_single_multiple_choice():
    solver = multiple_choice()
    state = simple_task_state(
        choices=["only one choice here"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate)

    assert new_state.output.completion == "ANSWER: A"
    assert new_state.user_prompt.text == MultipleChoiceTemplate.SINGLE_ANSWER.format(
        letters="A", question="What's the answer?", choices="A) only one choice here"
    )
    assert new_state.choices[0].correct is True


@pytest.mark.asyncio
async def test_maps_choices_without_shuffling():
    solver = multiple_choice()
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate)

    assert new_state.messages[-1].content == "ANSWER: A"
    assert new_state.user_prompt.text == MultipleChoiceTemplate.SINGLE_ANSWER.format(
        letters="A,B,C",
        question="What's the answer?",
        choices="A) choice 1\nB) choice 2\nC) choice 3",
    )
    assert [choice.correct for choice in new_state.choices] == [
        True,
        False,
        False,
    ]


@pytest.mark.asyncio
async def test_custom_template():
    solver = multiple_choice(template="Do this thing: {question} {choices}")
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate)

    assert new_state.messages[-1].content == "ANSWER: A"

    assert (
        new_state.user_prompt.text
        == "Do this thing: What's the answer? A) choice 1\nB) choice 2\nC) choice 3"
    )


@pytest.mark.asyncio
async def test_custom_template_raises_with_missing_fields():
    with pytest.raises(
        ValueError,
        match="The template must contain '{question}' and '{choices}' placeholders for string substitution.",
    ):
        multiple_choice(template="This template lacks substance")


@pytest.mark.asyncio
async def test_can_shuffle_choices_when_calling_the_model():
    async def generate_shuffled(state: TaskState):
        # Ensure that the choices are shuffled before we call the model
        assert "A) choice 3" in state.user_prompt.text
        assert "B) choice 2" in state.user_prompt.text
        assert "C) choice 1" in state.user_prompt.text
        return await generate(state=state)

    solver = multiple_choice(shuffle=Random(4))
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate_shuffled)

    assert new_state.output.completion == "ANSWER: C"
    assert new_state.messages[-1].content == "ANSWER: C"

    assert new_state.user_prompt.text == MultipleChoiceTemplate.SINGLE_ANSWER.format(
        letters="A,B,C",
        question="What's the answer?",
        choices="A) choice 1\nB) choice 2\nC) choice 3",
    )

    assert new_state.choices[0] == Choice(
        value="choice 3", correct=True, original_position=2
    )

    assert new_state.choices[1] == Choice(
        value="choice 2", correct=False, original_position=1
    )

    assert new_state.choices[2] == Choice(
        value="choice 1", correct=False, original_position=0
    )


@pytest.mark.asyncio
async def test_multiple_correct():
    generate = generate_for_multiple_correct(answers="ANSWER: AB")
    solver = multiple_choice(multiple_correct=True)
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate)

    assert new_state.output.completion == "ANSWER: AB"
    assert new_state.user_prompt.text == MultipleChoiceTemplate.MULTIPLE_ANSWER.format(
        letters="A,B,C",
        question="What's the answer?",
        choices="A) choice 1\nB) choice 2\nC) choice 3",
    )

    assert new_state.choices[0] == Choice(
        value="choice 1", correct=True, original_position=0
    )

    assert new_state.choices[1] == Choice(
        value="choice 2", correct=True, original_position=1
    )

    assert new_state.choices[2] == Choice(
        value="choice 3", correct=False, original_position=2
    )


@pytest.mark.asyncio
async def test_multiple_correct_model_generated_commas():
    generate = generate_for_multiple_correct(answers="ANSWER: B, C")
    solver = multiple_choice(multiple_correct=True)
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate)

    assert new_state.output.completion == "ANSWER: B, C"
    assert new_state.user_prompt.text == MultipleChoiceTemplate.MULTIPLE_ANSWER.format(
        letters="A,B,C",
        question="What's the answer?",
        choices="A) choice 1\nB) choice 2\nC) choice 3",
    )

    assert new_state.choices[0] == Choice(
        value="choice 1", correct=False, original_position=0
    )

    assert new_state.choices[1] == Choice(
        value="choice 2", correct=True, original_position=1
    )

    assert new_state.choices[2] == Choice(
        value="choice 3", correct=True, original_position=2
    )


@pytest.mark.asyncio
async def test_multiple_shuffled_answers_one_answer():
    # Given the shuffling before calling generate, the actual answer is actually A
    actual_generate = generate_for_multiple_correct(answers="ANSWER: C")

    async def generate_shuffled(state: TaskState):
        # Ensure that the choices are shuffled before we call the model
        assert "A) choice 3" in state.user_prompt.text
        assert "B) choice 2" in state.user_prompt.text
        assert "C) choice 1" in state.user_prompt.text
        return await actual_generate(state=state)

    solver = multiple_choice(multiple_correct=True, shuffle=Random(4))
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate_shuffled)

    assert new_state.output.completion == "ANSWER: A"
    assert new_state.messages[-1].content == "ANSWER: A"
    assert new_state.user_prompt.text == MultipleChoiceTemplate.MULTIPLE_ANSWER.format(
        letters="A,B,C",
        question="What's the answer?",
        choices="A) choice 1\nB) choice 2\nC) choice 3",
    )

    assert new_state.choices[0] == Choice(
        value="choice 3", correct=False, original_position=2
    )

    assert new_state.choices[1] == Choice(
        value="choice 2", correct=False, original_position=1
    )

    assert new_state.choices[2] == Choice(
        value="choice 1", correct=True, original_position=0
    )


@pytest.mark.asyncio
async def test_multiple_shuffled_answers_more():
    # Given the shuffling before calling generate, the actual answers are B, C
    actual_generate = generate_for_multiple_correct(answers="ANSWER: A, D")

    async def generate_shuffled(state: TaskState):
        # Ensure that the choices are shuffled before we call the model
        assert "A) choice 3" in state.user_prompt.text
        assert "B) choice 1" in state.user_prompt.text
        assert "C) choice 4" in state.user_prompt.text
        assert "D) choice 2" in state.user_prompt.text
        return await actual_generate(state=state)

    solver = multiple_choice(multiple_correct=True, shuffle=Random(4))
    state = simple_task_state(
        choices=["choice 1", "choice 2", "choice 3", "choice 4"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    new_state = await solver(state=state, generate=generate_shuffled)
    assert new_state.output.completion == "ANSWER: B, C"
    assert new_state.messages[-1].content == "ANSWER: B, C"
    assert new_state.user_prompt.text == MultipleChoiceTemplate.MULTIPLE_ANSWER.format(
        letters="A,B,C,D",
        question="What's the answer?",
        choices="A) choice 1\nB) choice 2\nC) choice 3\nD) choice 4",
    )

    assert new_state.choices[0] == Choice(
        value="choice 3", correct=True, original_position=2
    )

    assert new_state.choices[1] == Choice(
        value="choice 1", correct=False, original_position=0
    )

    assert new_state.choices[2] == Choice(
        value="choice 4", correct=False, original_position=3
    )

    assert new_state.choices[3] == Choice(
        value="choice 2", correct=True, original_position=1
    )


cot_complex = """
Let's approach this step-by-step:

1. First, we need to understand that the question is about what happens after fertilization has occurred. The sperm has already been injected into the egg, so we're dealing with post-fertilization issues.

2. Option B can be eliminated immediately because it talks about sperm binding to the egg, which has already happened in this scenario.

3. Option C is not correct because chromosomal recombination typically occurs during meiosis, which happens when gametes (sperm and egg) are formed, not after fertilization.

4. Now we're left with options A and D. Let's consider each:

   A) Epistatic interactions refer to how genes interact with each other. While this could potentially cause issues, it's not likely to be the main cause of zygote mortality.

   D) Chromosomal incompatibilities leading to failure of meiosis is more likely to be the main cause of zygote mortality.

5. Here's why D is the most probable answer:
   - Even though both species have the same number of chromosomes, the chromosomes themselves may be structurally different.
   - These structural differences can lead to problems during cell division.
   - The first cell division after fertilization is crucial for embryo development.
   - If the chromosomes can't properly align or separate due to incompatibilities, it would lead to cell division failure and subsequent death of the zygote.

6. While epistatic interactions (option A) could potentially cause issues later in development, chromosomal incompatibilities (option D) would cause problems immediately and be more likely to result in early zygote mortality.

Therefore, the most likely main cause of zygote mortality in this scenario would be chromosomal incompatibilities.

ANSWER: D"""


@pytest.mark.asyncio
async def test_cot_complex_text():
    # Tests and end to end multiple choice generate and score
    # with a real cot response that can trick our answer parsing

    solver = multiple_choice()
    state = simple_task_state(
        choices=["A", "B", "C", "D"],
        messages=[ChatMessageUser(content="What's the answer?", source="input")],
    )

    async def generate_cot_text(state: TaskState) -> TaskState:
        state.messages.append(ChatMessageAssistant(content=cot_complex))
        state.output = ModelOutput.from_content(model="model", content=cot_complex)
        return state

    new_state = await solver(state=state, generate=generate_cot_text)

    scorer = choice()
    result = await scorer(new_state, Target("D"))
    print(vars(result))

    assert result.value == CORRECT
    assert result.answer == "D"
