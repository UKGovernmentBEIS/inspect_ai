"""
Measuring Massive Multitask Language Understanding

Dan Hendrycks, Collin Burns, Steven Basart, Andy Zou,
Mantas Mazeika, Dawn Song, Jacob Steinhardt
https://arxiv.org/abs/2009.03300

Based on: https://github.com/openai/simple-evals/blob/main/mmlu_eval.py

# eval all subjects w/ 500 randomly selected samples
inspect eval mmlu.py@mmlu --limit 500

# add chain of thought
inspect eval mmlu.py@mmlu --limit 500 -T cot=true

# eval selected subjects
inspect eval mmlu.py@mmlu -T subjects=anatomy
inspect eval mmlu.py@mmlu -T subjects=astronomy
inspect eval mmlu.py@mmlu -T subjects=anatomy,astronomy
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, csv_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import answer
from inspect_ai.solver import multiple_choice


# map records to inspect sample
def record_to_sample(record):
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
    csv_file="datasets/mmlu.csv",
    sample_fields=record_to_sample,
    shuffle=True,
)


@task
def mmlu(subjects=[], cot=False):
    # filter dataset if requested
    subjects = subjects if isinstance(subjects, list) else [subjects]
    if len(subjects) > 0:
        task_dataset = dataset.filter(
            name=f"{dataset.name}-{'-'.join(subjects)}",
            predicate=lambda sample: sample.metadata["subject"] in subjects,
        )
    else:
        task_dataset = dataset

    # return task
    return Task(
        dataset=task_dataset,
        plan=multiple_choice(cot=cot),
        scorer=answer("letter"),
        config=GenerateConfig(temperature=0.5),
    )
