from typing import Protocol

from pydantic import JsonValue

from inspect_ai.log._log import EvalSpec
from inspect_ai.scorer._metric import SampleScore


class EarlyStopping(Protocol):
    def start_task(self, task: EvalSpec) -> None:
        """Called at the beginning of an eval run to register the tasks that will be run."""
        ...

    def schedule_sample(
        self, task: EvalSpec, id: str | int, epoch: int
    ) -> JsonValue | None:
        """Called prior to scheduling a sample (return False to prevent it from running)."""
        ...

    def complete_sample(
        self, task: EvalSpec, id: str | int, epoch: int, scores: dict[str, SampleScore]
    ) -> None:
        """Called when a sample is complete."""
        ...

    def complete_task(self, task: EvalSpec) -> JsonValue:
        """Called when the run is complete. Return a value for each task for inclusion in the task log file."""
        ...
