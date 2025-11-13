from random import random

from pydantic import JsonValue

from inspect_ai import EarlyStopping, Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.log._log import EvalSpec
from inspect_ai.scorer import SampleScore, match
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = r"""
Please note: In the following EXERCISE, it is important that you only respond with exactly "Yes" or "No"
"""


@task
def popularity():
    dataset = example_dataset(
        name="popularity",
        sample_fields=FieldSpec(
            input="question",
            target="answer_matching_behavior",
            metadata=["label_confidence"],
        ),
    )

    return Task(
        dataset=dataset,
        solver=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=[match()],
        early_stopping=TestEarlyStopping(),
    )


class TestEarlyStopping(EarlyStopping):
    def __init__(self) -> None:
        self._completed_samples: list[int | str] = []

    async def start_task(self, task: EvalSpec) -> None:
        """Called at the beginning of an eval run to register the tasks that will be run."""
        pass

    async def schedule_sample(
        self, task: EvalSpec, id: str | int, epoch: int
    ) -> JsonValue | None:
        """Called prior to scheduling a sample (return False to prevent it from running)."""
        # first check if this sample has no more epochs
        if id in self._completed_samples:
            return dict()

        if random() < 0.5:
            self._completed_samples.append(id)
            return dict()
        else:
            return None

    async def complete_sample(
        self, task: EvalSpec, id: str | int, epoch: int, scores: dict[str, SampleScore]
    ) -> None:
        """Called when a sample is complete."""
        pass

    async def complete_task(self, task: EvalSpec) -> JsonValue:
        """Called when the run is complete. Return a value for each task for inclusion in the task log file."""
        return dict()
