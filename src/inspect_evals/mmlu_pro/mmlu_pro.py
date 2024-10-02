"""MMLU-Pro: A More Robust and Challenging Multi-Task Language Understanding Benchmark

Yubo Wang, Xueguang Ma, Ge Zhang, Yuansheng Ni, Abhranil Chandra, Shiguang Guo,
Weiming Ren, Aaran Arulraj, Xuan He, Ziyan Jiang, Tianle Li, Max Ku, Kai Wang,
Alex Zhuang, Rongqi Fan, Xiang Yue, Wenhu Chen
https://arxiv.org/pdf/2406.01574

Based on: https://github.com/EleutherAI/lm-evaluation-harness/tree/main/lm_eval/tasks/mmlu_pro

# run with zero-shot (default)
inspect eval mmlu_pro/mmlu_pro.py

# run with fewshot samples
inspect eval mmlu_pro/mmlu_pro.py -T fewshot=5

# run for specific subjects
inspect eval mmlu_pro/mmlu_pro.py -T subjects=math,physics
"""

from typing import Any, Dict

from inspect_ai import Task, task
from inspect_ai.dataset import Dataset, Sample, hf_dataset
from inspect_ai.model import ChatMessageSystem
from inspect_ai.scorer import choice
from inspect_ai.solver import (
    Generate,
    Solver,
    TaskState,
    multiple_choice,
    solver,
)
from inspect_ai.util import resource

# Based on the prompt provided here:
# https://github.com/EleutherAI/lm-evaluation-harness/tree/main/lm_eval/tasks/mmlu_pro
SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE = """
The following are multiple choice questions (with answers) about {subject}. Think step by step and then finish your answer with 'ANSWER: $LETTER' (without quotes) where LETTER is the correct letter choice.

{examples}
""".strip()
# Based on MultipleChoiceTemplate.SINGLE_ANSWER provided in the multiple choice solver:
# https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/solver/_multiple_choice.py
USER_PROMPT_TEMPLATE = """Answer the following multiple choice question. The last line of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}. Think step by step before answering.

Question:
{question}
Options:
{choices}
""".strip()


@task
def mmlu_pro(
    subjects: str | list[str] = [],
    fewshot: int = 0,
) -> Task:
    """Inspect task implementing the MMLU-Pro benchmark.

    Args:
        subjects (list[str]): List of subjects to evaluate on.
        fewshot (int): Number of few shot examples to use.
    """
    dataset = hf_dataset(
        "TIGER-Lab/MMLU-Pro",
        split="test",
        trust=True,
        sample_fields=record_to_sample,
        shuffle=True,
    )
    # Subset the data based on subject
    subjects = subjects if isinstance(subjects, list) else [subjects]
    dataset = filter_dataset(dataset=dataset, subjects=subjects)

    return Task(
        dataset=dataset,
        solver=mmlu_pro_solver(fewshot=fewshot),
        scorer=choice(),
    )


@solver
def mmlu_pro_system_message(dataset: Dataset, fewshot: int) -> Solver:
    """Solver which inserts a system message for MMLU-Pro based on sample into the conversation.

    The new message will go after other system messages (if there
    are none it will be inserted at the beginning of the conversation).

    Args:
       dataset (Dataset): Dataset consisting of fewshot samples.
       fewshot (int): Number of few shot examples to use.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # Subset the data based on subject
        subject = state.metadata["subject"]
        fewshot_samples = filter_dataset(dataset=dataset, subjects=[subject])

        # Select fewshot samples
        assert (
            len(fewshot_samples) >= fewshot
        ), f"""The dataset ({len(fewshot_samples)}) does not have the requested number of fewshot samples ({fewshot}), reduce 'fewshot'."""
        if fewshot < len(fewshot_samples):
            fewshot_samples = fewshot_samples[:fewshot]

        message = SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE.format(
            subject=subject,
            examples="\n\n".join(
                [sample_to_fewshot(sample=sample) for sample in fewshot_samples]
            ),
        )
        content = resource(message)
        state.messages.insert(0, ChatMessageSystem(content=content))

        return state

    return solve


def filter_dataset(dataset: Dataset, subjects: list[str]) -> Dataset:
    """Filters the MMLU-Pro dataset by subjects.

    Args:
        dataset (Dataset): Dataset object to be filtered.
        subjects (List): List of subjects to filter on.
    """
    # Filter dataset by subjects, if required
    if len(subjects) > 0:
        dataset = dataset.filter(
            name=f"{dataset.name}_subject-{'-'.join(subjects)}",
            predicate=lambda sample: sample.metadata["subject"] in subjects
            if sample.metadata is not None
            else False,
        )

    return dataset


def mmlu_pro_solver(
    fewshot: int,
) -> list[Solver]:
    solver = [multiple_choice(template=USER_PROMPT_TEMPLATE, shuffle=False)]

    if fewshot:
        fewshot_samples = hf_dataset(
            "TIGER-Lab/MMLU-Pro",
            split="validation",
            trust=True,
            sample_fields=record_to_sample,
        )
        solver.insert(
            0,
            mmlu_pro_system_message(
                dataset=fewshot_samples,
                fewshot=fewshot,
            ),
        )

    return solver


def record_to_sample(record: Dict[str, Any]) -> Sample:
    return Sample(
        input=record["question"],
        choices=record["options"],
        target=record["answer"],
        id=record["question_id"],
        metadata={
            "cot_content": record["cot_content"],
            "subject": record["category"].lower(),
        },
    )


def sample_to_fewshot(sample: Sample) -> str:
    q_str = f"""Question:\n{str(sample.input)}"""
    options = sample.choices if sample.choices is not None else []
    opt_str_list = []
    for i, opt in enumerate(options):
        opt_str_list.append(f"""{chr(65 + i)}) {opt}""")
    opt_str = "\n".join(opt_str_list)
    opt_str = f"""Options:\n{opt_str}"""
    ans_str = sample.metadata["cot_content"] if sample.metadata is not None else ""
    ans_str = ans_str.replace("The answer is", "ANSWER:")
    ans_opt = ans_str.split("ANSWER:")[-1].split(".")[0].strip().strip("(").strip(")")
    ans_str = ans_str.replace(f"ANSWER: ({ans_opt})", f"ANSWER: {ans_opt}")
    final_str = "\n".join([q_str, opt_str, ans_str])

    return final_str
