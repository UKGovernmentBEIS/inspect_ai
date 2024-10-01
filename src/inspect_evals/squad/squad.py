"""
Know What You Don't Know: Unanswerable Questions for SQuAD

Extractive reading comprehension systems can often locate the correct answer to a question in a context document, but they also tend to make unreliable guesses on questions for which the correct answer is not stated in the context. Existing datasets either focus exclusively on answerable questions, or use automatically generated unanswerable questions that are easy to identify. To address these weaknesses, we present SQuAD 2.0, the latest version of the Stanford Question Answering Dataset (SQuAD). SQuAD 2.0 combines existing SQuAD data with over 50,000 unanswerable questions written adversarially by crowdworkers to look similar to answerable ones. To do well on SQuAD 2.0, systems must not only answer questions when possible, but also determine when no answer is supported by the paragraph and abstain from answering.

Pranav Rajpurkar, Robin Jia, Percy Liang
https://arxiv.org/abs/1806.03822

# eval race_h
inspect eval inspect_evals/squad
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import exact, f1
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = """
Using only the context provided in the question itself, you are tasked with answering a question in as few words as possible.
If the question is unanswerable, answer with 'unanswerable' in all lowercase.
"""


@task
def squad() -> Task:
    """Inspect Task implementation of the SQuAD benchmark"""
    dataset = hf_dataset(
        path="rajpurkar/squad_v2",
        split="validation",
        sample_fields=record_to_sample,
        shuffle=True,
    )

    return Task(
        dataset=dataset,
        solver=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=[f1(), exact()],
    )


def record_to_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        input=format_input(record),
        target=record["answers"]["text"]
        if record["answers"]["text"]
        else "unanswerable",
        id=record["id"],
    )


def format_input(record: dict[str, Any]) -> str:
    passage_str = f"""Context: {record["context"]}"""
    question_str = f"""Question: {record["question"]}"""
    return "\n".join([passage_str, question_str])
