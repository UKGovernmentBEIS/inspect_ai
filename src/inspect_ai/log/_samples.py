import asyncio
import contextlib
from contextvars import ContextVar
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
        *,
        task: str,
        model: str,
        sample: Sample,
        epoch: int,
        message_limit: int | None,
        token_limit: int | None,
        time_limit: int | None,
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
        self.message_limit = message_limit
        self.token_limit = token_limit
        self.time_limit = time_limit
        self.fails_on_error = fails_on_error
        self.total_messages = 0
        self.total_tokens = 0
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
    *,
    task: str,
    model: str,
    sample: Sample,
    epoch: int,
    message_limit: int | None,
    token_limit: int | None,
    time_limit: int | None,
    fails_on_error: bool,
    transcript: Transcript,
) -> AsyncGenerator[ActiveSample, None]:
    # create the sample
    active = ActiveSample(
        task=task,
        model=model,
        sample=sample,
        epoch=epoch,
        message_limit=message_limit,
        token_limit=token_limit,
        time_limit=time_limit,
        sandboxes=await sandbox_connections(),
        fails_on_error=fails_on_error,
        transcript=transcript,
    )

    _active_samples.append(active)
    _sample_active.set(active)
    try:
        yield active
    finally:
        active.completed = datetime.now().timestamp()
        _active_samples.remove(active)
        _sample_active.set(None)


def sample_active() -> ActiveSample | None:
    return _sample_active.get(None)


def set_active_sample_token_limit(token_limit: int | None) -> None:
    active = sample_active()
    if active:
        active.token_limit = token_limit


def set_active_sample_total_tokens(total_tokens: int) -> None:
    active = sample_active()
    if active:
        active.total_tokens = total_tokens


def set_active_sample_message_limit(message_limit: int | None) -> None:
    active = sample_active()
    if active:
        active.message_limit = message_limit


def set_active_sample_total_messages(total_messages: int) -> None:
    active = sample_active()
    if active:
        active.total_messages = total_messages


_sample_active: ContextVar[ActiveSample | None] = ContextVar(
    "_sample_active", default=None
)


def active_samples() -> list[ActiveSample]:
    return _active_samples


_active_samples: list[ActiveSample] = []
