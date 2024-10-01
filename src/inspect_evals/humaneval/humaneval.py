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
from typing import Any

from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    mean,
    scorer,
    std,
)
from inspect_ai.solver import TaskState, generate
from inspect_ai.util import ExecResult, sandbox

# repeat each problem n times
NUM_EPOCHS = 5

# timeout for verification/scoring
VERIFY_TIMEOUT = 30

# instruction prepended to code problem
INSTRUCTION = """
Read the following function signature and docstring, and fully implement
the function described. Your response should only contain the code for
this function.\n
"""


@task
def humaneval(sandbox: str = "docker") -> Task:
    """
    Inspect Task implementation for the HumanEval benchmark

    Args:
        sandbox (String): The sandbox to use for this evaluation
    """
    return Task(
        dataset=hf_dataset(
            path="openai_humaneval", split="test", sample_fields=record_to_sample
        ),
        epochs=Epochs(NUM_EPOCHS, ["mean", "pass_at_1", "pass_at_2", "pass_at_5"]),
        solver=[generate()],
        scorer=verify(),
        sandbox=sandbox,
    )


@scorer(metrics=[mean(), std()])
def verify() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # extract answer from completion and format for verification
        answer = find_code(state.output.completion)
        code = [
            state.metadata["prompt"],
            answer,
            "\n",
            state.metadata["test"],
            "\n",
            "".join(["check(", state.metadata["entry_point"], ")"]),
        ]

        # verify (returns error status if incorrect)
        try:
            result = await sandbox().exec(
                cmd=["python", "-c", "".join(code)],
                timeout=VERIFY_TIMEOUT,
            )
        except TimeoutError:
            result = ExecResult(False, 1, "", "Verification timed out.")

        # return score w/ model answer + scoring details
        return Score(
            value=CORRECT if result.success else INCORRECT,
            answer=answer,
            explanation="".join(
                ["The following verification code was executed:\n\n"]
                + ["```python\n\n"]
                + code
                + ["\n```\n"]
                + [f"\nThe submission was incorrect\n\n{result.stderr}"]
                if not result.success
                else [""]
            ),
        )

    return score


# extract code from completion (removing markdown and/or signature)
def find_code(completion: str) -> str:
    pattern_1 = re.compile(r"```python\n(.*?)```", re.DOTALL)
    pattern_2 = re.compile(r"```\n(.*?)```", re.DOTALL)
    matches = pattern_1.findall(completion) + pattern_2.findall(completion)
    extracted_answer = matches[0] if len(matches) >= 1 else completion
    # remove signature
    extracted_answer = extracted_answer[extracted_answer.find(":\n    ") + 2 :]
    return str(extracted_answer)


# map humaneval record into inspect sample
def record_to_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        id=record["task_id"],
        input=INSTRUCTION + record["prompt"],
        target=record["canonical_solution"],
        metadata={
            "prompt": record["prompt"],
            "test": record["test"],
            "entry_point": record["entry_point"],
        },
    )
