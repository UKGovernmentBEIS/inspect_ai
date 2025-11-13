from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field, JsonValue

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer._metric import SampleScore


class EarlyStop(BaseModel):
    """Directive to stop a sample early."""

    reason: str | None = Field(default=None)
    """Reason for the early stop."""

    metadata: dict[str, JsonValue] | None = Field(default=None)
    """Metadata related to early stop."""


class StoppedSample(BaseModel):
    """Record of early stop for a sample/epoch."""

    id: str | int
    """Sample dataset id."""

    epoch: int
    """Sample epoch."""

    early_stop: EarlyStop
    """Early stop directive."""


class EarlyStoppingSummary(BaseModel):
    manager: str
    """Name of early stopping manager."""

    stopped_samples: list[StoppedSample]
    """Samples that were stopped early."""

    metadata: dict[str, JsonValue]
    """Metadata about early stopping"""


class EarlyStopping(Protocol):
    async def start_task(self, task: "EvalSpec") -> str:
        """Called at the beginning of an eval run to register the tasks that will be run.

        Args:
            task: Task metadata.

        Returns:
            Name of early stopping manager.
        """
        ...

    async def schedule_sample(
        self, task: "EvalSpec", id: str | int, epoch: int
    ) -> EarlyStop | None:
        """Called prior to scheduling a sample to cheeck for an early stop.

        Args:
            task: Task metadata.
            id: Sample dataset id.
            epoch: Sample epoch.

        Returns:
            `EarlyStop` if the sample should be stopped early, otherwise `None`.
        """
        ...

    async def complete_sample(
        self,
        task: "EvalSpec",
        id: str | int,
        epoch: int,
        scores: dict[str, "SampleScore"],
    ) -> None:
        """Called when a sample is complete.

        Args:
           task: Task metadata.
           id: Sample dataset id.
           epoch: Sample epoch.
           scores: Scores for this sample.
        """
        ...

    async def complete_task(self, task: "EvalSpec") -> dict[str, JsonValue]:
        """Called when the task is complete.

        Args:
           task: Task metadata.

        Returns:
            Metadata (e.g. diagnostics) about early stopping.
        """
        ...
