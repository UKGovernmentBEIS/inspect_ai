"""DROP: A Reading Comprehension Benchmark Requiring Discrete Reasoning Over Paragraphs

Dheeru Dua, Yizhong Wang, Pradeep Dasigi,
Gabriel Stanovsky, Sameer Singh, and Matt Gardner
https://arxiv.org/pdf/1903.00161

Based on: https://github.com/openai/simple-evals/blob/main/drop_eval.py
and https://github.com/EleutherAI/lm-evaluation-harness/tree/main/lm_eval/tasks/drop

# run with default fewshot samples (3)
inspect eval drop/drop.py

# run with more or no fewshot samples
inspect eval drop/drop.py -T fewshot=5
inspect eval drop/drop.py -T fewshot=false
"""

import re
import string
from typing import Dict, List, Tuple, Union

import numpy as np
from scipy.optimize import linear_sum_assignment  # type: ignore

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import Score, Target, bootstrap_std, mean, scorer
from inspect_ai.scorer._classification import max_f1_score
from inspect_ai.solver import (
    TaskState,
    generate,
    prompt_template,
    system_message,
)

# Based on the prompt provided here: https://github.com/openai/simple-evals/blob/main/drop_eval.py#L261C13-L283C91
SYSTEM_PROMPT_TEMPLATE = """
You will be asked to read a passage and answer a question.
""".strip()

SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE = """
You will be asked to read a passage and answer a question. Some examples of passages and Q&A are provided below.

Examples
{examples}
""".strip()
USER_PROMPT_TEMPLATE = """
Your Task
---
{prompt}

Think step by step, then write a line of the form "Answer: $ANSWER" at the end of your response.
""".strip()

# Borrowed from: https://github.com/openai/simple-evals/blob/main/common.py#L24
ANSWER_PATTERN = r"(?i)Answer\s*:\s*([^\n]+)"


@task
def drop(
    fewshot: int = 3,
    fewshot_seed: int = 42,
) -> Task:
    """Inspect task implementing the DROP benchmark.

    Arguments:
        fewshot (int): Number of few shot examples to use.
        fewshot_seed (int): Random seed for sampling few shot examples.
    """
    return Task(
        dataset=hf_dataset(
            "EleutherAI/drop",
            split="validation",
            trust=True,
            sample_fields=record_to_sample,
        ),
        plan=build_plan(fewshot=fewshot, fewshot_seed=fewshot_seed),
        scorer=drop_f1_scorer(),
    )


@scorer(metrics=[mean(), bootstrap_std()])
def drop_f1_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        # Get generated answer and extract relevant answer text
        answer = state.output.completion
        match = re.search(ANSWER_PATTERN, answer)
        answer = match.group(1) if match else answer

        # Get target answers (convert str elm to tuple by splitting on "|")
        ref_answers = [el for elm in target.target for el in elm.split("|")]

        # Compute exact match (EM) and F1 score
        f1_score = max_f1_score(answer, ref_answers)

        # F1 score reported as main aggregated metric, EM score added to metadata
        return Score(
            value=f1_score,
            answer=answer,
            metadata={
                "gold_answers": ref_answers,
            },
        )

    return score


def build_plan(
    fewshot: int,
    fewshot_seed: int,
) -> List:
    """Builds plan using various solvers for the DROP task.

    Arguments:
        fewshot (int): Number of few shot examples to use.
        fewshot_seed (int): Random seed for sampling few shot examples.
    """
    # Add system message based on zero-shot or few-shot prompting
    if fewshot:
        fewshot_samples = hf_dataset(
            "EleutherAI/drop",
            split="train",
            trust=True,
            sample_fields=record_to_sample,
            shuffle=True,
            seed=fewshot_seed,
            limit=fewshot,
        )
        sys_msg = system_message(
            SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE.format(
                examples="\n\n".join(
                    [sample_to_fewshot(sample) for sample in fewshot_samples]
                )
            )
        )
    else:
        sys_msg = system_message(SYSTEM_PROMPT_TEMPLATE)

    plan = [
        sys_msg,
        prompt_template(USER_PROMPT_TEMPLATE),
        generate(),
    ]

    return plan


def record_to_sample(record: Dict) -> Sample:
    return Sample(
        input=format_input(record),
        target=format_target(record),
        id=record["query_id"],
    )


def format_input(doc: Dict) -> str:
    passage_str = f"""Passage: {doc["passage"]}"""
    question_str = f"""Question: {doc["question"]}"""
    answer_str = """Answer:"""
    input_str = "\n".join([passage_str, question_str, answer_str])
    return input_str


def format_target(doc: Dict) -> List[str]:
    target = get_answers(doc)
    # Convert each tuple to str, since 'target' only accepts 'str' or 'List[str]'.
    target = ["|".join(elm) for elm in target]
    return target


def sample_to_fewshot(sample: Sample) -> str:
    target = sample.target[0].split("|")[0]
    return f"""{sample.input} {target}"""


# Copied from
# https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/drop/utils.py#L23C1-L49C19
def get_answers(doc: Dict) -> List:
    def _flatten_validated_answers(validated_answers: Dict) -> List[Dict]:
        """Flattens a dict of lists of validated answers.

        {"number": ['1', '8'], ...}
        -> [{"number": ['1'], ...}, {"number": ['8'], ...}]
        """
        valid_answers = []
        for i in range(len(validated_answers["number"])):
            valid_answers.append(
                {
                    "number": validated_answers["number"][i],
                    "date": validated_answers["date"][i],
                    "spans": validated_answers["spans"][i],
                }
            )
        return valid_answers

    answers = []
    answers_set = set()
    candidates = [doc["answer"]] + _flatten_validated_answers(doc["validated_answers"])
    for candidate in candidates:
        answer = parse_answer(candidate)
        if answer in answers_set:
            continue
        answers_set.add(answer)
        answers.append(answer)
    return answers


def parse_answer(answer: Dict) -> Tuple:
    # NOTE: Everything is returned as a tuple for uniformity and hashability.
    if answer["number"] != "":
        return (str(answer["number"]),)
    if answer["spans"] != []:
        return tuple(answer["spans"])
    return (
        " ".join(
            [answer["date"]["day"], answer["date"]["month"], answer["date"]["year"]]
        ).strip(),
    )
