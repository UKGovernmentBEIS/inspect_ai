from typing import Any

from datasets import Dataset  # type: ignore

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser, GenerateConfig
from inspect_ai.scorer import choice, model_graded_fact
from inspect_ai.solver import generate, multiple_choice, prompt_template

from .utils import create_content_and_answers_list, load_and_concatenate_datasets


# Allow multiple-choice tasks to be run separately
@task
def mmmu_multiple_choice() -> Task:
    combined_dataset = load_and_concatenate_datasets(subjects_list)
    return mmmu_task_multiple_choice(combined_dataset)


# Allow open-ended tasks to be run separately
@task
def mmmu_open() -> Task:
    combined_dataset = load_and_concatenate_datasets(subjects_list)
    return mmmu_task_open(combined_dataset)


MULT_CHOICE_PROMPT = r"""
Answer with the option's letter from the given choices directly.
{prompt}
""".strip()


def mmmu_task_multiple_choice(dataset: Dataset) -> Task:
    multiple_choice_questions_hf = dataset.filter(
        lambda example: example["question_type"] == "multiple-choice"
    )
    multiple_choice_questions_inspect = MemoryDataset(
        samples=[
            record_to_sample_multiple_choice(data)
            for data in multiple_choice_questions_hf
        ],
        name="MMMU-Multiple-Choice",
        location="MMMU/MMMU",
    )

    return Task(
        dataset=multiple_choice_questions_inspect,
        solver=[prompt_template(MULT_CHOICE_PROMPT), multiple_choice()],
        scorer=choice(),
        config=GenerateConfig(temperature=0),
    )


OPEN_PROMPT = r"""
Answer the question using a single word or phrase.
{prompt}
""".strip()


def mmmu_task_open(dataset: Dataset) -> Task:
    open_ended_questions_hf = dataset.filter(
        lambda example: example["question_type"] == "open"
    )
    open_ended_questions_inspect = MemoryDataset(
        samples=[record_to_sample_open_ended(data) for data in open_ended_questions_hf],
        name="MMMU-Open-Ended",
        location="MMMU/MMMU",
    )

    return Task(
        dataset=open_ended_questions_inspect,
        solver=[prompt_template(OPEN_PROMPT), generate()],
        scorer=model_graded_fact(),
        config=GenerateConfig(temperature=0),
    )


subjects_list = [
    "Accounting",
    "Agriculture",
    "Architecture_and_Engineering",
    "Art",
    "Art_Theory",
    "Basic_Medical_Science",
    "Biology",
    "Chemistry",
    "Clinical_Medicine",
    "Computer_Science",
    "Design",
    "Diagnostics_and_Laboratory_Medicine",
    "Economics",
    "Electronics",
    "Energy_and_Power",
    "Finance",
    "Geography",
    "History",
    "Literature",
    "Manage",
    "Marketing",
    "Materials",
    "Math",
    "Mechanical_Engineering",
    "Music",
    "Pharmacy",
    "Physics",
    "Psychology",
    "Public_Health",
    "Sociology",
]


# Map records to Inspect Sample for multiple-choice questions
def record_to_sample_multiple_choice(record: dict[str, Any]) -> Sample:
    content_list, answers_list = create_content_and_answers_list(record)

    return Sample(
        input=[ChatMessageUser(content=content_list)],
        choices=answers_list,
        target=record["answer"],
        metadata={
            "subfield": record["subfield"],
            "explanation": record["explanation"],
            "img_type": record["img_type"],
            "topic_difficulty": record["topic_difficulty"],
        },
    )


# Map records to Inspect Sample for open-ended questions
def record_to_sample_open_ended(record: dict[str, Any]) -> Sample:
    content_list, _ = create_content_and_answers_list(record)

    return Sample(
        input=[ChatMessageUser(content=content_list)],
        target=record["answer"],
        metadata={
            "subfield": record["subfield"],
            "explanation": record["explanation"],
            "img_type": record["img_type"],
            "topic_difficulty": record["topic_difficulty"],
        },
    )
