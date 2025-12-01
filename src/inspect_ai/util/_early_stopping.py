from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field, JsonValue

if TYPE_CHECKING:
    from inspect_ai.dataset._dataset import Sample
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer._metric import SampleScore


class EarlyStop(BaseModel):
    """Directive to stop a sample early."""

    id: str | int
    """Sample dataset id."""

    epoch: int
    """Sample epoch."""

    reason: str | None = Field(default=None)
    """Reason for the early stop."""

    metadata: dict[str, JsonValue] | None = Field(default=None)
    """Metadata related to early stop."""


class EarlyStoppingSummary(BaseModel):
    """Summary of early stopping applied to task."""

    manager: str
    """Name of early stopping manager."""

    early_stops: list[EarlyStop]
    """Samples that were stopped early."""

    metadata: dict[str, JsonValue]
    """Metadata about early stopping"""


class EarlyStopping(Protocol):
    """Early stopping manager for skipping selected samples/epochs."""

    async def start_task(
        self, task: "EvalSpec", samples: list["Sample"], epochs: int
    ) -> str:
        """Called at the beginning of an eval run to register the tasks that will be run.

        Args:
            task: Task metadata.
            samples: List of samples that will be executed for this task.
            epochs: Number of epochs to run for each sample.

        Returns:
            Name of early stopping manager.
        """
        ...

    async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
        """Called prior to scheduling a sample to cheeck for an early stop.

        Args:
            id: Sample dataset id.
            epoch: Sample epoch.

        Returns:
            `EarlyStop` if the sample should be stopped early, otherwise `None`.
        """
        ...

    async def complete_sample(
        self,
        id: str | int,
        epoch: int,
        scores: dict[str, "SampleScore"],
    ) -> None:
        """Called when a sample is complete.

        Args:
           id: Sample dataset id.
           epoch: Sample epoch.
           scores: Scores for this sample.
        """
        ...

    async def complete_task(self) -> dict[str, JsonValue]:
        """Called when the task is complete.

        Returns:
            Metadata (e.g. diagnostics) about early stopping.
        """
        ...
