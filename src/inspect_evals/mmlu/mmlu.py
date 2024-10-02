"""
Measuring Massive Multitask Language Understanding

Dan Hendrycks, Collin Burns, Steven Basart, Andy Zou,
Mantas Mazeika, Dawn Song, Jacob Steinhardt
https://arxiv.org/abs/2009.03300

Based on: https://github.com/openai/simple-evals/blob/main/mmlu_eval.py

# eval all subjects w/ 500 randomly selected samples
inspect eval inspect_evals/mmlu --limit 500

# add chain of thought
inspect eval inspect_evals/mmlu --limit 500 -T cot=true

# eval selected subjects
inspect eval inspect_evals/mmlu -T subjects=anatomy
inspect eval inspect_evals/mmlu -T subjects=astronomy
inspect eval inspect_evals/mmlu -T subjects=anatomy,astronomy
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, csv_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice


# map records to inspect sample
def record_to_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        input=record["Question"],
        choices=[
            str(record["A"]),
            str(record["B"]),
            str(record["C"]),
            str(record["D"]),
        ],
        target=record["Answer"],
        metadata={"subject": record["Subject"]},
    )


# read dataset globally so it can be shared by all of the tasks
# (shuffle so that --limit draws from multiple subjects)
dataset = csv_dataset(
    csv_file="https://openaipublic.blob.core.windows.net/simple-evals/mmlu.csv",
    sample_fields=record_to_sample,
    auto_id=True,
    shuffle=True,
)


@task
def mmlu(subjects: str | list[str] = [], cot: bool = False) -> Task:
    """
    Inspect Task implementation for MMLU

    Args:
        subjects (str | list[str]): Subjects to filter to
        cot (bool): Whether to use chain of thought
    """
    # filter dataset if requested
    subjects = subjects if isinstance(subjects, list) else [subjects]
    if len(subjects) > 0:
        task_dataset = dataset.filter(
            name=f"{dataset.name}-{'-'.join(subjects)}",
            predicate=lambda sample: sample.metadata is not None
            and sample.metadata.get("subject") in subjects,
        )
    else:
        task_dataset = dataset

    solver = multiple_choice(cot=cot)

    return Task(
        dataset=task_dataset,
        solver=solver,
        scorer=choice(),
        config=GenerateConfig(temperature=0.5),
    )
