"""
Instruction-Following Evaluation for Large Language Models

Jeffrey Zhou, Tianjian Lu, Swaroop Mishra, Siddhartha Brahma, Sujoy Basu, Yi Luan,
Denny Zhou, Le Hou
https://arxiv.org/pdf/2311.07911

Based on: https://github.com/google-research/google-research/tree/master/instruction_following_eval
"""

from typing import cast

import numpy as np
from instruction_following_eval.evaluation import (  # type: ignore
    InstructionResult,
    test_instruction_following_loose,
    test_instruction_following_strict,
)

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import Metric, Score, Scorer, Target, Value, metric, scorer
from inspect_ai.solver import TaskState, generate


@task
def ifeval():
    return Task(
        dataset=hf_dataset(
            path="google/IFEval", split="train", sample_fields=record_to_sample
        ),
        solver=[generate()],
        scorer=instruction_following(),
    )


@metric
def if_metric() -> Metric:
    def metric(scores: list[Score]) -> Value:
        statistics = []
        prompt_keys = ["prompt_level_strict", "prompt_level_loose"]
        instruct_keys = ["inst_level_strict", "inst_level_loose"]
        final_keys = [
            "prompt_strict_acc",
            "prompt_strict_std",
            "prompt_loose_acc",
            "prompt_loose_std",
            "inst_strict_acc",
            "inst_strict_std",
            "inst_loose_acc",
            "inst_loose_std",
            "final_acc",
        ]

        # calculate prompt-level accuracies/stds
        for key in prompt_keys:
            score_lst = [cast(dict, score.value)[key] for score in scores]
            statistics.append(np.mean(score_lst).item())
            statistics.append(np.std(score_lst).item())

        # calculate instruction-level accuracies/stds
        for key in instruct_keys:
            flattened = []
            for score in scores:
                value = cast(dict, score.value)
                num_correct = int(value[key])
                num_incorrect = int(value["num_instructions"] - value[key])
                flattened.extend([True] * num_correct + [False] * num_incorrect)
            statistics.append(np.mean(flattened).item())
            statistics.append(np.std(flattened).item())

        # calculate the final accuracy (excluding the std in the calculation)
        statistics.append(
            np.mean([statistics[i] for i in range(0, len(statistics), 2)]).item()
        )

        return {k: v for k, v in zip(final_keys, statistics)}

    return metric


@scorer(metrics=[if_metric()])
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
