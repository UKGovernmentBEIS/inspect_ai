"""
Instruction-Following Evaluation for Large Language Models

Jeffrey Zhou, Tianjian Lu, Swaroop Mishra, Siddhartha Brahma, Sujoy Basu, Yi Luan,
Denny Zhou, Le Hou
https://arxiv.org/pdf/2311.07911

Based on: https://github.com/google-research/google-research/tree/master/instruction_following_eval
"""

import numpy as np
from instruction_following_eval.evaluation import (
    InstructionResult,
    test_instruction_following_loose,
    test_instruction_following_strict,
)

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import (
    Metric,
    Score,
    Scorer,
    Target,
    metric,
    scorer,
)
from inspect_ai.solver import TaskState, generate


@task
def ifeval():
    return Task(
        dataset=hf_dataset(
            path="google/IFEval", split="train", sample_fields=record_to_sample
        ),
        plan=[generate()],
        scorer=instruction_following(),
    )


def prompt_level(key: str, reduction: str) -> Metric:
    """Compute the prompt level statistics"""

    def metric(scores: list[Score]) -> float:
        return getattr(np, reduction)([score.value[key] for score in scores]).item()

    return metric


def inst_level(key: str, reduction: str) -> Metric:
    """Compute the instruction level statistics"""

    def metric(scores: list[Score]) -> float:
        flattened = []
        for score in scores:
            flattened.extend(
                [True] * int(score.value[key])
                + [False] * int(score.value["num_instructions"] - score.value[key])
            )
        return getattr(np, reduction)(flattened).item()

    return metric


@metric
def prompt_level_strict_acc() -> Metric:
    return prompt_level("prompt_level_strict", "mean")


@metric
def prompt_level_strict_std() -> Metric:
    return prompt_level("prompt_level_strict", "std")


@metric
def prompt_level_loose_acc() -> Metric:
    return prompt_level("prompt_level_loose", "mean")


@metric
def prompt_level_loose_std() -> Metric:
    return prompt_level("prompt_level_loose", "std")


@metric
def inst_level_strict_acc() -> Metric:
    return inst_level("inst_level_strict", "mean")


@metric
def inst_level_strict_std() -> Metric:
    return inst_level("inst_level_strict", "std")


@metric
def inst_level_loose_acc() -> Metric:
    return inst_level("inst_level_loose", "mean")


@metric
def inst_level_loose_std() -> Metric:
    return inst_level("inst_level_loose", "std")


@scorer(
    metrics=[
        prompt_level_strict_acc(),
        prompt_level_strict_std(),
        prompt_level_loose_acc(),
        prompt_level_loose_std(),
        inst_level_strict_acc(),
        inst_level_strict_std(),
        inst_level_loose_acc(),
        inst_level_loose_std(),
    ]
)
def instruction_following() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # construct the input to IFEval's evaluation functions using the data class
        eval_input = InstructionResult(
            state.sample_id,
            state.metadata["instruction_id_list"],
            state.metadata["prompt"],
            state.output.completion,
            state.metadata["kwargs"],
        )

        # retrieve evaluated outputs
        out_strict = test_instruction_following_strict(eval_input)
        out_loose = test_instruction_following_loose(eval_input)
        ret_value = {
            "prompt_level_strict": out_strict.follow_all_instructions,
            "inst_level_strict": sum(out_strict.follow_instruction_list),
            "prompt_level_loose": out_loose.follow_all_instructions,
            "inst_level_loose": sum(out_loose.follow_instruction_list),
            "num_instructions": len(out_loose.follow_instruction_list),
        }

        # return score with resulting outputs, model answer, and the
        # expected instructions
        return Score(
            value=ret_value,
            answer=state.output.completion,
            explanation=" ".join(state.metadata["instruction_id_list"]),
        )

    return score


# map ifeval record into inspect sample
def record_to_sample(record):
    new_kwargs = {}
    for index in range(len(record["instruction_id_list"])):
        # remove None values from kwargs to avoid unexpected keyword argument errors
        # in build_description method from the IFEval package.
        kwargs = {k: v for k, v in record["kwargs"][index].items() if v}
        new_kwargs[index] = kwargs

    return Sample(
        id=record["key"],
        input=record["prompt"],
        metadata={
            "prompt": record["prompt"],
            "instruction_id_list": record["instruction_id_list"],
            "kwargs": new_kwargs,
        },
    )
