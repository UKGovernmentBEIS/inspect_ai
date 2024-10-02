"""
PIQA (Physical Interaction: Question Answering)

Reasoning about Physical Commonsense in Natural Language
Yonatan Bisk, Rowan Zellers, Ronan Le Bras, Jianfeng Gao, Yejin Choi
https://arxiv.org/abs/1911.11641

# eval piqa validation set
inspect eval inspect_evals/piqa
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice

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
def piqa() -> Task:
    """Inspect Task implementation of PIQA"""
    dataset = hf_dataset(
        path="piqa",
        sample_fields=record_to_sample,
        trust=True,
        split="validation",
        auto_id=True,
        shuffle=True,
    )

    return Task(
        dataset=dataset,
        solver=[multiple_choice(template=TEMPLATE)],
        scorer=choice(),
    )


def record_to_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        input=record["goal"],
        target="A" if record["label"] == 0 else "B",
        choices=[record["sol1"], record["sol2"]],
    )
