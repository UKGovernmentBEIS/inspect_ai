import re
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.model import ChatMessage, ChatMessageUser, ContentImage, ContentText
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    AnswerPattern,
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.scorer._pattern import match_first
from inspect_ai.solver import Generate, Solver, TaskState, solver

SINGLE_ANSWER_TEMPLATE = r"""
Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}.

{question}

{choices}
""".strip()

FREEFORM_TEMPLATE = r"""
Answer the following question. The entire content of your response should be of the following format: 'ANSWER: $ANSWER' (without quotes) where $ANSWER is your answer.

{question}
"""


@task
def mathvista() -> Task:
    dataset = hf_dataset(
        path="AI4Math/MathVista",
        split="testmini",
        sample_fields=record_to_sample,
        trust=True,
        shuffle=True,
    )

    return Task(
        dataset=dataset,
        solver=[mathvista_solver()],
        scorer=mathvista_scorer(),
    )


@scorer(metrics=[accuracy(), stderr()])
def mathvista_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        match = re.search(
            AnswerPattern.LETTER
            if state.metadata["question_type"] == "multi_choice"
            else AnswerPattern.LINE,
            state.output.completion,
            re.IGNORECASE,
        )
        if match:
            # scoring pattern found in response
            groups = match.groups()
            found_match = match_first(matches=groups, target=target, ignore_case=True)

            if found_match is None and len(groups) == 1:
                answer = groups[0]
            else:
                answer = found_match

            return Score(
                value=CORRECT if found_match else INCORRECT,
                answer=answer,
                explanation=state.output.completion,
            )

        else:
            # didn't find the scoring pattern
            return Score(
                value=INCORRECT,
                explanation="Scoring pattern not matched in output: "
                + f"{state.output.completion}",
            )

    return score


@solver
def mathvista_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.metadata["question_type"] == "multi_choice":
            state.user_prompt.text = state.choices.prompt(
                question=state.user_prompt.text,
                template=SINGLE_ANSWER_TEMPLATE,
            )

            return await generate(state)

        elif state.metadata["question_type"] == "free_form":
            state.user_prompt.text = FREEFORM_TEMPLATE.format(
                question=state.user_prompt.text
            )
            return await generate(state)

        else:
            raise ValueError(
                "Question type must be one of 'free_form' or 'multi_choice'. Received: %s"
                % state.metadata["question_type"]
            )

    return solve


def record_to_sample(record: dict) -> Sample:
    # extract image
    image = Path(record["image"])
    if not image.exists():
        print(f"Extracting {image}")
        image.parent.mkdir(exist_ok=True)
        with open(image, "wb") as file:
            file.write(record["decoded_image"]["bytes"])

    message: list[ChatMessage] = [
        ChatMessageUser(
            content=[
                ContentText(text=record["question"])
                if record["question_type"] == "multi_choice"
                else ContentText(text=record["query"]),
                ContentImage(image=record["image"]),
            ]
        )
    ]

    if record["question_type"] == "multi_choice":
        return Sample(
            input=message,
            choices=record["choices"],
            target=get_multi_choice_as_letter(record),
            id=record["pid"],
            metadata={
                "question_type": record["question_type"],
                "answer_type": record["answer_type"],
                **record["metadata"],
            },
        )

    elif record["question_type"] == "free_form":
        return Sample(
            input=message,
            target=record["answer"],
            id=record["pid"],
            metadata={
                "precision": record["precision"],
                "question_type": record["question_type"],
                "answer_type": record["answer_type"],
                **record["metadata"],
            },
            files={f"image:{record['image']}": record["image"]},
        )
    else:
        raise ValueError(f"Unexpected question_type: {record['question_type']}")


def get_multi_choice_as_letter(record: dict) -> str:
    choices = record["choices"]
    labels = [chr(i) for i in range(ord("a"), ord("a") + len(choices))]

    choices = dict(zip(labels, choices))

    answer = record["answer"]
    target = list(choices.values()).index(answer)
    return chr(ord("A") + int(target))
