"""
BoolQ

Exploring the Surprising Difficulty of Natural Yes/No Questions
Christopher Clark, Kenton Lee, Ming-Wei Chang, Tom Kwiatkowski, Michael Collins,
Kristina Toutanova
https://arxiv.org/abs/1905.10044

# Run against validations boolq dataset
inspect eval boolq.py
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import pattern
from inspect_ai.solver import generate, prompt_template

TEMPLATE = r"""
Answer the following question with either Yes or No. Include nothing else in your response.

Question: {prompt}
"""


def record_to_sample(record):
    if record["answer"]:
        target = "Yes"
    else:
        target = "No"

    return Sample(input=record["question"], target=target)


@task
def boolq():
    dataset = hf_dataset(
        path="boolq",
        sample_fields=record_to_sample,
        split="validation",
        shuffle=True,
    )

    return Task(
        dataset=dataset,
        plan=[prompt_template(template=TEMPLATE), generate()],
        scorer=pattern(r"(Yes|No).?\Z"),
    )
