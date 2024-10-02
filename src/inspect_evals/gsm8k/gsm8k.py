"""
Training Verifiers to Solve Math Word Problems

Karl Cobbe, Vineet Kosaraju, Mohammad Bavarian, Mark Chen, Heewoo Jun, Lukasz Kaiser, Matthias Plappert, Jerry Tworek, Jacob Hilton, Reiichiro Nakano, Christopher Hesse, John Schulman
https://arxiv.org/abs/2110.14168

# run with default fewshots (10)
inspect eval gsm8k.py

# run with less  or no fewshots
inspect eval gsm8k.py -T fewshot=5
inspect eval gsm8k.py -T fewshot=false
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import match
from inspect_ai.solver import generate, prompt_template, system_message

# setup for problem + instructions for providing answer
MATH_PROMPT_TEMPLATE = """
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.

Reasoning:
""".strip()


@task
def gsm8k(fewshot: int = 10, fewshot_seed: int = 42) -> Task:
    """Inspect Task definition for the GSM8K benchmark

    Args:
        fewshot (int): The number of few shots to include
        fewshot_seed (int): The seed for generating few shots
    """
    # build solver dynamically (may or may not be doing fewshot)
    solver = [prompt_template(MATH_PROMPT_TEMPLATE), generate()]
    if fewshot:
        fewshots = hf_dataset(
            path="gsm8k",
            data_dir="main",
            split="train",
            sample_fields=record_to_sample,
            auto_id=True,
            shuffle=True,
            seed=fewshot_seed,
            limit=fewshot,
        )
        solver.insert(
            0,
            system_message(
                "\n\n".join([sample_to_fewshot(sample) for sample in fewshots])
            ),
        )

    # define task
    return Task(
        dataset=hf_dataset(
            path="gsm8k",
            data_dir="main",
            split="test",
            sample_fields=record_to_sample,
        ),
        solver=solver,
        scorer=match(numeric=True),
    )


def record_to_sample(record: dict[str, Any]) -> Sample:
    DELIM = "####"
    input = record["question"]
    answer = record["answer"].split(DELIM)
    target = answer.pop().strip()
    reasoning = DELIM.join(answer)
    return Sample(input=input, target=target, metadata={"reasoning": reasoning.strip()})


def sample_to_fewshot(sample: Sample) -> str:
    if sample.metadata:
        return (
            f"{sample.input}\n\nReasoning:\n"
            + f"{sample.metadata['reasoning']}\n\n"
            + f"ANSWER: {sample.target}"
        )
    else:
        return ""
