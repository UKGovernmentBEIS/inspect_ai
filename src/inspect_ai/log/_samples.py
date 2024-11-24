import asyncio
import contextlib
from datetime import datetime
from typing import AsyncGenerator, Literal

from shortuuid import uuid

from inspect_ai.dataset._dataset import Sample
from inspect_ai.util._sandbox import SandboxConnection
from inspect_ai.util._sandbox.context import sandbox_connections

from ._transcript import Transcript


class ActiveSample:
    def __init__(
        self,
        task: str,
        model: str,
        sample: Sample,
        epoch: int,
        fails_on_error: bool,
        transcript: Transcript,
        sandboxes: dict[str, SandboxConnection],
    ) -> None:
        self.id = uuid()
        self.started = datetime.now().timestamp()
        self.completed: float | None = None
        self.task = task
        self.model = model
        self.sample = sample
        self.epoch = epoch
        self.fails_on_error = fails_on_error
        self.transcript = transcript
        self.sandboxes = sandboxes
        self._sample_task = asyncio.current_task()
        self._interrupt_action: Literal["score", "error"] | None = None

    @property
    def execution_time(self) -> float:
        completed = (
            self.completed if self.completed is not None else datetime.now().timestamp()
        )
        return completed - self.started

    def interrupt(self, action: Literal["score", "error"]) -> None:
        self._interrupt_action = action
        assert self._sample_task
        self._sample_task.cancel()

    @property
    def interrupt_action(self) -> Literal["score", "error"] | None:
        return self._interrupt_action


def init_active_samples() -> None:
    _active_samples.clear()


@contextlib.asynccontextmanager
async def active_sample(
    task: str,
    model: str,
    sample: Sample,
    epoch: int,
    fails_on_error: bool,
    transcript: Transcript,
) -> AsyncGenerator[ActiveSample, None]:
    # create the sample
    active = ActiveSample(
        task=task,
        model=model,
        sample=sample,
        epoch=epoch,
        sandboxes=await sandbox_connections(),
        fails_on_error=fails_on_error,
        transcript=transcript,
    )

    _active_samples.append(active)
    try:
        yield active
    finally:
        active.completed = datetime.now().timestamp()
        _active_samples.remove(active)


def active_samples() -> list[ActiveSample]:
    return _active_samples


_active_samples: list[ActiveSample] = []
