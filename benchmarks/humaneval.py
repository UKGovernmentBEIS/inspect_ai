"""
HumanEval: Hand-Written Evaluation Set

Mark Chen, Jerry Tworek, Heewoo Jun, Qiming Yuan, Henrique Ponde de Oliveira Pinto,
Jared Kaplan, Harri Edwards, Yuri Burda, Nicholas Joseph, Greg Brockman, Alex Ray,
Raul Puri, Gretchen Krueger, Michael Petrov, Heidy Khlaaf, Girish Sastry,
Pamela Mishkin, Brooke Chan, Scott Gray, Nick Ryder, Mikhail Pavlov, Alethea Power,
Lukasz Kaiser, Mohammad Bavarian, Clemens Winter, Philippe Tillet,
Felipe Petroski Such, Dave Cummings, Matthias Plappert, Fotios Chantzis,
Elizabeth Barnes, Ariel Herbert-Voss, William Hebgen Guss, Alex Nichol, Alex Paino,
Nikolas Tezak, Jie Tang, Igor Babuschkin, Suchir Balaji, Shantanu Jain,
William Saunders, Christopher Hesse, Andrew N. Carr, Jan Leike, Josh Achiam,
Vedant Misra, Evan Morikawa, Alec Radford, Matthew Knight, Miles Brundage,
Mira Murati, Katie Mayer, Peter Welinder, Bob McGrew, Dario Amodei, Sam McCandlish,
Ilya Sutskever, Wojciech Zaremba
https://arxiv.org/pdf/2107.03374

Based on: https://github.com/openai/simple-evals/blob/main/humaneval_eval.py
"""

import re
from collections import defaultdict

import numpy as np

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Metric,
    Score,
    Scorer,
    Target,
    metric,
    scorer,
)
from inspect_ai.solver import Generate, TaskState, generate, solver
from inspect_ai.util import subprocess

INSTRUCTION = "Read the following function signature and docstring, and fully implement the function described. Your response should only contain the code for this function.\n"
TIMEOUT = 20
NUM_EPOCHS = 5


def _per_sample_collator(scores: list[Score]) -> dict[str, list[float]]:
    id_to_values = defaultdict(list)
    ret_dict = defaultdict(dict)
    for score in scores:
        id_to_values[score.metadata["ID"]].append(1.0 if score.text == CORRECT else 0.0)

    for key in id_to_values:
        correct, total = sum(id_to_values[key]), len(id_to_values[key])
        accuracy = correct / total
        ret_dict[key]["correct"] = correct
        ret_dict[key]["total"] = total
        ret_dict[key]["accuracy"] = accuracy

    return ret_dict


def pass_at_k(k: int, stat: str) -> Metric:
    def _metric(correct: int, total: int) -> float:
        if total - correct < k:
            return 1.0
        return 1.0 - np.prod(1.0 - k / np.arange(total - correct + 1, total + 1))

    def batch_aggregate_metric(scores: list[Score]) -> float:
        id_to_stats = _per_sample_collator(scores)
        list_of_metrics = []
        for id in id_to_stats:
            n, c = id_to_stats[id]["total"], id_to_stats[id]["correct"]
            list_of_metrics.append(_metric(c, n))
        if stat == "mean":
            return np.mean(list_of_metrics).item()
        else:
            return np.std(list_of_metrics).item()

    return batch_aggregate_metric


@metric("accuracy")
def sample_aggregate_accuracy() -> Metric:
    def metric(scores: list[Score]) -> float:
        id_to_stats = _per_sample_collator(scores)
        list_of_metrics = [id_to_stats[k]["accuracy"] for k in id_to_stats]
        return np.mean(list_of_metrics).item()

    return metric


@metric("pass@1:mean")
def pass_at_1_mean() -> Metric:
    return pass_at_k(1, "mean")


@metric("pass@2:mean")
def pass_at_2_mean() -> Metric:
    return pass_at_k(2, "mean")


@metric("pass@5:mean")
def pass_at_5_mean() -> Metric:
    return pass_at_k(5, "mean")


@metric("pass@1:std")
def pass_at_1_std() -> Metric:
    return pass_at_k(1, "std")


@metric("pass@2:std")
def pass_at_2_std() -> Metric:
    return pass_at_k(2, "std")


@metric("pass@5:std")
def pass_at_5_std() -> Metric:
    return pass_at_k(5, "std")


@solver
def find_code():
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        pattern = re.compile(r"```python\n(.*?)```", re.DOTALL)
        matches = pattern.findall(state.output.completion)
        extracted_answer = matches[0] if len(matches) >= 1 else state.output.completion
        extracted_answer = extracted_answer[
            extracted_answer.find(":\n    ") + 2 :
        ]  # remove signature
        state.output.completion = extracted_answer
        return state

    return solve


@scorer(
    metrics=[
        sample_aggregate_accuracy(),
        pass_at_1_mean(),
        pass_at_1_std(),
        pass_at_2_mean(),
        pass_at_2_std(),
        pass_at_5_mean(),
        pass_at_5_std(),
    ]
)
def verify_correctness() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        code = [
            state.metadata["prompt"],
            state.output.completion,
            "\n",
            state.metadata["test"],
            "\n",
            "".join(["check(", state.metadata["entry_point"], ")"]),
        ]

        result = await subprocess(
            ["python", "-c", "".join(code)],
            timeout=TIMEOUT,
        )

        metadata = {"ID": state.metadata["id"]}
        if not result.success:
            metadata["Error"] = result.stderr

        return Score(
            value=CORRECT if result.success else INCORRECT,
            answer=state.output.completion,
            explanation="".join(["The following code was executed \n"] + code),
            metadata=metadata,
        )

    return score


def record_to_sample(record):
    return Sample(
        id=record["task_id"],
        input=INSTRUCTION + record["prompt"],
        target=record["canonical_solution"],
        metadata={
            "prompt": record["prompt"],
            "test": record["test"],
            "entry_point": record["entry_point"],
            "id": record["task_id"],
        },
    )


@task
def humaneval():
    dataset = hf_dataset(
        path="openai_humaneval",
        split="test",
        sample_fields=record_to_sample,
        trust=True,
    )
    return Task(
        dataset=dataset,
        plan=[generate(), find_code()],
        scorer=verify_correctness(),
        epochs=NUM_EPOCHS,
    )
