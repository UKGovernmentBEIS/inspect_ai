"""
RACE: Large-scale ReAding Comprehension Dataset From Examinations

Evaluation on RACE-H, the subset of the dataset corresponding to high school examinations, is implemented

Guokun Lai, Qizhe Xie, Hanxiao Liu, Yiming Yang, Eduard Hovy
https://arxiv.org/abs/1704.04683

# eval race-h
inspect eval race-h.py
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice

TEMPLATE = r"""
Answer the following multiple-choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}.

You are provided with a passage, a question based on the passage, and four choices for the answer. Exactly one of the choices is correct.

Passage:
{question}

Choices:
{choices}
""".strip()


@task
def race_h():
    dataset = hf_dataset(
        path="ehovy/race",
        name="high",
        sample_fields=record_to_sample,
        split="test",
        shuffle=True,
    )

    return Task(
        dataset=dataset,
        plan=[multiple_choice(template=TEMPLATE)],
        scorer=choice(),
        config=GenerateConfig(temperature=0.0),
    )


def record_to_sample(record):
    return Sample(
        input=record["article"] + "\n\nQuestion:\n" + record["question"],
        target=record["answer"],
        choices=record["options"],
    )
