"""
Think you have Solved Question Answering? Try ARC, the AI2 Reasoning Challenge

Peter Clark, Isaac Cowhey, Oren Etzioni, Tushar Khot, Ashish Sabharwal, Carissa Schoenick, Oyvind Tafjord
https://arxiv.org/abs/1803.05457

# run all subsets
inspect eval arc.py

# run specific subsets
inspect eval arc.py@arc_easy
inspect eval arc.py@arc_challenge
"""

from typing import Any, Literal

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice


def arc_task(dataset_name: Literal["ARC-Easy", "ARC-Challenge"]) -> Task:
    """Inspect task implementing the ARC benchmark.

    Args:
        dataset_name (Literal["ARC-Easy", "ARC-Challenge"]): The dataset to use
    """
    return Task(
        dataset=hf_dataset(
            path="allenai/ai2_arc",
            name=dataset_name,
            split="test",
            sample_fields=record_to_sample,
        ),
        solver=multiple_choice(),
        scorer=choice(),
    )


@task
def arc_easy() -> Task:
    """Inspect task implementing the ARC-Easy benchmark."""
    return arc_task("ARC-Easy")


@task
def arc_challenge() -> Task:
    """Inspect task implementing the ARC-Challenge benchmark."""
    return arc_task("ARC-Challenge")


def record_to_sample(record: dict[str, Any]) -> Sample:
    # read the labels and text
    choices = record["choices"]
    choices = dict(zip(choices["label"], choices["text"]))

    # determine the target then normalize to letter
    answerKey = record["answerKey"]
    target_index = list(choices.keys()).index(answerKey)
    target = chr(ord("A") + target_index)

    # return sample
    return Sample(
        input=record["question"], choices=list(choices.values()), target=target
    )
