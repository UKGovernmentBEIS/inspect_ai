import contextlib
from datetime import datetime
from typing import AsyncGenerator

from shortuuid import uuid

from inspect_ai.dataset._dataset import Sample

from ._transcript import Transcript


class ActiveSample:
    def __init__(
        self, task: str, model: str, sample: Sample, epoch: int, transcript: Transcript
    ) -> None:
        self.id = uuid()
        self.started = datetime.now().timestamp()
        self.completed: float | None = None
        self.task = task
        self.model = model
        self.sample = sample
        self.epoch = epoch
        self.transcript = transcript

    @property
    def execution_time(self) -> float:
        completed = (
            self.completed if self.completed is not None else datetime.now().timestamp()
        )
        return completed - self.started


def init_active_samples() -> None:
    _active_samples.clear()


@contextlib.asynccontextmanager
async def active_sample(sample: ActiveSample) -> AsyncGenerator[None, None]:
    _active_samples.append(sample)
    try:
        yield
    finally:
        sample.completed = datetime.now().timestamp()
        _active_samples.remove(sample)


def active_samples() -> list[ActiveSample]:
    return _active_samples


_active_samples: list[ActiveSample] = []
