"""
PIQA (Physical Interaction: Question Answering)

Reasoning about Physical Commonsense in Natural Language
Yonatan Bisk, Rowan Zellers, Ronan Le Bras, Jianfeng Gao, Yejin Choi
https://arxiv.org/abs/1911.11641

# eval piqa validation set
inspect eval piq.py
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice


def record_to_sample(record):
    return Sample(
        input=record["goal"],
        target="A" if record["label"] == 0 else "B",
        choices=[record["sol1"], record["sol2"]],
    )


TEMPLATE = r"""
The entire content of your response should be of the following format: 'ANSWER:
$LETTER' (without quotes) where LETTER is one of {letters}.

Given either a question or a statement followed by two possible solutions
labelled A and B, choose the most appropriate solution. If a question is given,
the solutions answer the question. If a statement is given, the solutions
explain how to achieve the statement.

{question}

{choices}
""".strip()


@task
def piqa():
    dataset = hf_dataset(
        path="piqa",
        sample_fields=record_to_sample,
        trust=True,
        split="validation",
        shuffle=True,
    )

    return Task(
        dataset=dataset,
        plan=[multiple_choice(template=TEMPLATE)],
        scorer=choice(),
    )
