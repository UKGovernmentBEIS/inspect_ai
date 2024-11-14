import contextlib
from time import monotonic
from typing import AsyncGenerator

from shortuuid import uuid

from inspect_ai.dataset._dataset import Sample

from ._transcript import Transcript


class ActiveSample:
    def __init__(
        self, task: str, model: str, sample: Sample, transcript: Transcript
    ) -> None:
        self.id = uuid()
        self.started = monotonic()
        self.task = task
        self.model = model
        self.sample = sample
        self.transcript = transcript

    started: float
    task: str
    model: str
    sample: Sample
    transcript: Transcript


def init_active_samples() -> None:
    _active_samples.clear()


@contextlib.asynccontextmanager
async def active_sample(sample: ActiveSample) -> AsyncGenerator[None, None]:
    _active_samples.append(sample)
    try:
        yield
    finally:
        _active_samples.remove(sample)


def active_samples() -> list[ActiveSample]:
    return _active_samples


_active_samples: list[ActiveSample] = []
