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

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice


def record_to_sample(record):
    # read the labels and text
    choices = record["choices"]
    choices = dict(zip(choices["label"], choices["text"]))

    # determine the target then normalize to letter
    answerKey = record["answerKey"]
    target = list(choices.keys()).index(answerKey)
    target = chr(ord("A") + int(target))

    # return sample
    return Sample(
        input=record["question"], choices=list(choices.values()), target=target
    )


def arc_task(dataset_name):
    return Task(
        dataset=hf_dataset(
            path="allenai/ai2_arc",
            name=dataset_name,
            split="test",
            sample_fields=record_to_sample,
        ),
        plan=multiple_choice(),
        scorer=choice(),
    )


@task
def arc_easy():
    return arc_task("ARC-Easy")


@task
def arc_challenge():
    return arc_task("ARC-Challenge")
