from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import exact, f1
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = """
Using only the context provided in the question itself, you are tasked with answering a question in as few words as possible.
If the question is unanswerable, answer with 'unanswerable' in all lowercase.
"""


@task
def squad():
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


def record_to_sample(record):
    return Sample(
        input=format_input(record),
        target=record["answers"]["text"]
        if record["answers"]["text"]
        else "unanswerable",
        id=record["id"],
    )


def format_input(record) -> str:
    passage_str = f"""Context: {record["context"]}"""
    question_str = f"""Question: {record["question"]}"""
    return "\n".join([passage_str, question_str])
