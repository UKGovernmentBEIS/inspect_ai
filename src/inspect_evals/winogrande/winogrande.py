"""WINOGRANDE: An Adversarial Winograd Schema Challenge at Scale

Keisuke Sakaguchi, Ronan Le Bras, Chandra Bhagavatula, Yejin Choi
https://arxiv.org/pdf/1907.10641

The prompt template is based on the multiple choice template in openai simple evals:
https://github.com/openai/simple-evals/blob/main/mmlu_eval.py

# run with default fewshot samples (5)
inspect eval winogrande/winogrande.py

# run with more or no fewshot samples
inspect eval winogrande/winogrande.py -T fewshot=5
inspect eval winogrande/winogrande.py -T fewshot=false

# run with different subset of the dataset
inspect eval winogrande/winogrande.py -T dataset_name=winogrande_l
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import choice
from inspect_ai.solver import (
    Solver,
    multiple_choice,
    system_message,
)

# Assumption: "A" and "B" are the option letters.
ANSWER_TO_LETTER = {"1": "A", "2": "B"}
BLANK_TAG = "[BLANK]"


# Based on the prompt provided here:
# https://huggingface.co/datasets/meta-llama/Meta-Llama-3.1-8B-evals/viewer/Meta-Llama-3.1-8B-evals__winogrande__details?row=0
SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE = (
    f"""The following are multiple choice questions, with answers on the best logical completion to replace {BLANK_TAG} by {list(ANSWER_TO_LETTER.values())[0]} or {list(ANSWER_TO_LETTER.values())[1]}."""
    + """\n\n{examples}\n"""
)
# Based on MultipleChoiceTemplate.SINGLE_ANSWER provided in the multiple choice solver:
# https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/solver/_multiple_choice.py
USER_PROMPT_TEMPLATE = (
    f"""Answer the following multiple choice question by choosing the best logical option to replace the {BLANK_TAG}."""
    + """ The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}.\n\n{question}\n{choices}\n"""
)


@task
def winogrande(
    dataset_name: str = "winogrande_xl",
    fewshot: int = 5,
    fewshot_seed: int = 42,
) -> Task:
    """Inspect task implementing the WinoGrande benchmark.

    Arguments:
        dataset_name (str): Subset of the dataset to be used.
        fewshot (int): Number of few shot examples to use.
        fewshot_seed (int): Random seed for sampling few shot examples.
    """
    return Task(
        dataset=hf_dataset(
            "allenai/winogrande",
            name=dataset_name,
            split="validation",
            trust=True,
            sample_fields=record_to_sample,
        ),
        solver=winogrande_solver(
            dataset_name=dataset_name, fewshot=fewshot, fewshot_seed=fewshot_seed
        ),
        scorer=choice(),
        config=GenerateConfig(max_tokens=64),
    )


def winogrande_solver(
    dataset_name: str,
    fewshot: int,
    fewshot_seed: int,
) -> list[Solver]:
    solver = [multiple_choice(template=USER_PROMPT_TEMPLATE, shuffle=False)]

    if fewshot:
        fewshot_samples = hf_dataset(
            "allenai/winogrande",
            name=dataset_name,
            split="train",
            trust=True,
            sample_fields=record_to_sample,
            auto_id=True,
            shuffle=True,
            seed=fewshot_seed,
            limit=fewshot,
        )
        solver.insert(
            0,
            system_message(
                SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE.format(
                    examples="\n\n".join(
                        [sample_to_fewshot(sample=sample) for sample in fewshot_samples]
                    )
                )
            ),
        )

    return solver


def record_to_sample(record: dict[str, Any]) -> Sample:
    input = f"""Sentence: {record["sentence"].replace("_", BLANK_TAG)}"""
    target = ANSWER_TO_LETTER[record["answer"]]
    choices = [record["option1"], record["option2"]]  # Order is IMP

    return Sample(
        input=input,
        choices=choices,
        target=target,
    )


def sample_to_fewshot(sample: Sample) -> str:
    sent_str = str(sample.input)
    choices = sample.choices if sample.choices is not None else []
    assert (
        len(choices) == 2
    ), "Number of choices should be 2 for the winogrande dataset."
    opt1_str = f"""{list(ANSWER_TO_LETTER.values())[0]}) {choices[0]}"""
    opt2_str = f"""{list(ANSWER_TO_LETTER.values())[1]}) {choices[1]}"""
    ans_str = f"""ANSWER: {sample.target}"""
    final_str = "\n".join([sent_str, opt1_str, opt2_str, ans_str])

    return final_str
