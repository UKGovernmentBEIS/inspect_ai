"""
HellaSwag: Can a Machine Really Finish Your Sentence?

Rowan Zellers, Ari Holtzman, Yonatan Bisk, Ali Farhadi, Yejin Choi
https://arxiv.org/abs/1905.07830
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice, system_message

SYSTEM_MESSAGE = """
Choose the most plausible continuation for the story.
"""


def record_to_sample(record):
    return Sample(
        input=record["ctx"],
        target=chr(ord("A") + int(record["label"])),
        choices=record["endings"],
        metadata=dict(source_id=record["source_id"]),
    )


@task
def hellaswag():
    # dataset
    dataset = hf_dataset(
        path="hellaswag",
        split="validation",
        sample_fields=record_to_sample,
        trust=True,
        shuffle=True,
    )

    # define task
    return Task(
        dataset=dataset,
        plan=[system_message(SYSTEM_MESSAGE), multiple_choice()],
        scorer=choice(),
    )
