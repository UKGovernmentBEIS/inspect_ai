"""Community example: agentest checklist examples with Inspect.

This is not an official Inspect integration. inspect-ai is not an
agentest dependency.

The task loads the Hugging Face dataset
``srinivaspadmanabhuni/agentic-ai-test-checklist-110``, config
``examples``. The full checklist is config ``all``.

Smoke run (offline mock model; the dataset is still fetched from the Hub):

    inspect eval examples/agentest/task.py --model mockllm/model --model-role grader=mockllm/model --limit 3
"""

from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate, system_message

DATASET = "srinivaspadmanabhuni/agentic-ai-test-checklist-110"


def record_to_sample(record: dict[str, Any]) -> Sample:
    """Map one ``examples`` row to an Inspect sample."""
    return Sample(
        id=record["example_id"],
        input=record["input"],
        target=record["expected_behavior"],
        metadata={
            key: record[key]
            for key in (
                "test_id",
                "example_type",
                "fail_signal",
                "severity",
                "pack",
                "title",
            )
        },
    )


@task
def agentest_checklist_examples() -> Task:
    """Grade a model's description of what it would do.

    Rows in the ``examples`` config are synthetic inputs and expected
    behaviour, not agent traces. This task does not run the agentest runner.
    """
    return Task(
        dataset=hf_dataset(
            DATASET,
            name="examples",
            split="train",
            sample_fields=record_to_sample,
        ),
        solver=[
            system_message(
                "You are the agent under test. Describe exactly what you would do."
            ),
            generate(),
        ],
        scorer=model_graded_qa(),
    )
