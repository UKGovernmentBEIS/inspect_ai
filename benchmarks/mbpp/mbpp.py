"""
MBPP: Mostly Basic Python Problems

Jacob Austin, Augustus Odena, Maxwell Nye, Maarten Bosma, Henryk Michalewski,
David Dohan, Ellen Jiang, Carrie Cai, Michael Terry, Quoc Le, Charles Sutton
https://arxiv.org/pdf/2108.07732

Based on: https://github.com/google-research/google-research/tree/master/mbpp

# run the eval on the sanitized test split
inspect eval benchmarks/mbpp/mbpp.py
"""
import math  # Used by some assert statements by MBPP.

from datasets import load_dataset

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import (CORRECT, INCORRECT, Score, Target, accuracy,
                               scorer, stderr)
from inspect_ai.solver import TaskState, generate, prompt_template

PROMPT_TEMPLATE = """
You are an expert Python programmer. You will be given a task, and the tests that your code must pass.
Write the Python function to solve the task. Do not give additional explanations, just output the
Python function. Only use imports that are included in Python's standard library.
"""


def record_to_sample(record):
    return Sample(
        input=record["prompt"],
        target=record["test_list"],
        id=record["task_id"],
        metadata={
            "prompt": record["prompt"],
            "test_list": record["test_list"],
            "test_list_str": "\n".join(record["test_list"]),
            "source_file": record["source_file"],
            "code": record["code"],
            "test_imports": record["test_imports"],
            "task_id": record["task_id"],
        }
    )


@scorer(metrics=[accuracy(), stderr()])
def code_acceptance():
    async def score(state: TaskState, target: Target):

        # It is assumed that generated output is of the form:
        # ```python
        # [code output]
        # ```
        raw_generated_code = state.output.completion
        generated_code = raw_generated_code.replace("```python", "").replace("```", "")

        explanation = ""
        passed = True
        try:
            # Pass globals() as exec() may not work for functions that are recursive
            # or use other functions that will still be defined afterwards.
            exec(generated_code, globals())
        except Exception as e:
            explanation += f"Could not execute generated code. Error: {e}\n"
            passed = False

        if passed:
            for i, test_case in enumerate(target.target):
                try:
                    exec(test_case, globals())
                except AssertionError:
                    passed = False
                    explanation += f"Failed Test Case {i+1}: {test_case}. Assertion failed.\n"
                except Exception as e:
                    passed = False
                    explanation += f"Failed Test Case {i+1}: {test_case}. Error: {e}\n"

        if passed:
            explanation += "All test cases passed.\n"

        explanation += "The raw, generated output is shown below: \n"
        explanation += raw_generated_code

        return Score(
            value=CORRECT if passed else INCORRECT,
            answer=generated_code,
            explanation=explanation
        )

    return score


@task
def mbpp(
):
    template = PROMPT_TEMPLATE
    template += """
# For example:"""

    few_shot_dataset = load_dataset(
        "google-research-datasets/mbpp",
        "full",
        split="prompt",
    )
    # Task IDs 2, 3, 4 are from
    # https://github.com/google-research/google-research/tree/master/mbpp
    few_shot_ids = [2, 3, 4]
    few_shot_dataset = few_shot_dataset.filter(lambda row: row['task_id'] in few_shot_ids)

    # Few shot prompts are based off
    # https://github.com/huangd1999/AgentCoder/blob/main/prompts/mbpp_prompt.txt
    for i, sample in enumerate(few_shot_dataset):
        test_cases = "\n".join(sample["test_list"])
        template += f"""

## Prompt {i+1}:
```python
{sample['text']}
```

## Test Case {i+1}:
```python
{test_cases}
```

## Completion {i+1}:
```python
{sample['code']}
```"""

    template += """
# Now, do it for the following task.

## Prompt:
```python
{prompt}
```

## Test Case:
```python
{test_list_str}
```

## Completion:
"""

    dataset = hf_dataset(
        "google-research-datasets/mbpp",
        "sanitized",
        sample_fields=record_to_sample,
        split="test",
    )

    return Task(
        dataset=dataset,
        plan=[
            prompt_template(template),
            generate(),
        ],
        scorer=code_acceptance(),
        config=GenerateConfig(temperature=0.0),
    )
