"""
PubMedQA: A Dataset for Biomedical Research Question Answering

# inspect eval inspect_evals/pubmedqa
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice

TEMPLATE = r"""
Answer the following multiple choice question about medical knowledge given the context.
The entire content of your response should be of the following format: 'ANSWER: $LETTER'
(without quotes) where LETTER is one of {letters}.

{question}

{choices}
""".strip()


@task
def pubmedqa() -> Task:
    """Inspect Task implementation of the PubMedQA Eval"""
    dataset = hf_dataset(
        path="bigbio/pubmed_qa",
        # Note: Each of 10 folds has a different `train` and `validation` set,
        # but all 10 have the same `test` set.
        name="pubmed_qa_labeled_fold0_bigbio_qa",
        sample_fields=record_to_sample,
        trust=True,
        split="test",
    )

    return Task(
        dataset=dataset,
        solver=[multiple_choice(template=TEMPLATE)],
        scorer=choice(),
    )


def record_to_sample(record: dict[str, Any]) -> Sample:
    choices = {
        "yes": "A",
        "no": "B",
        "maybe": "C",
    }
    abstract = record["context"]
    question = record["question"]
    return Sample(
        input=f"Context: {abstract}\nQuestion: {question}",
        target=choices[record["answer"][0].lower()],  # provided as e.g. ['yes']
        id=record["id"],
        choices=record["choices"],  # always ['yes, 'no', 'maybe']
    )
