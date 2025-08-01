import contextlib
from contextvars import ContextVar
from datetime import datetime
from typing import AsyncGenerator, Iterator, Literal

from anyio.abc import TaskGroup
from shortuuid import uuid

from inspect_ai.dataset._dataset import Sample
from inspect_ai.util._sandbox import SandboxConnection
from inspect_ai.util._sandbox.context import sandbox_connections

from ._transcript import ModelEvent, Transcript


class ActiveSample:
    def __init__(
        self,
        *,
        task: str,
        log_location: str,
        model: str,
        sample: Sample,
        epoch: int,
        message_limit: int | None,
        token_limit: int | None,
        time_limit: int | None,
        working_limit: int | None,
        fails_on_error: bool,
        transcript: Transcript,
        sandboxes: dict[str, SandboxConnection],
        tg: TaskGroup,
    ) -> None:
        self.id = uuid()
        self.started: float | None = None
        self.completed: float | None = None
        self.task = task
        self.log_location = log_location
        self.model = model
        self.sample = sample
        self.epoch = epoch
        self.message_limit = message_limit
        self.token_limit = token_limit
        self.time_limit = time_limit
        self.working_limit = working_limit
        self.fails_on_error = fails_on_error
        self.total_messages = 0
        self.total_tokens = 0
        self.transcript = transcript
        self.sandboxes = sandboxes
        self._interrupt_action: Literal["score", "error"] | None = None
        self.tg = tg

    @property
    def running_time(self) -> float:
        if self.started is not None:
            completed = (
                self.completed
                if self.completed is not None
                else datetime.now().timestamp()
            )
            return completed - self.started
        else:
            return 0

    def interrupt(self, action: Literal["score", "error"]) -> None:
        self._interrupt_action = action

    @property
    def interrupt_action(self) -> Literal["score", "error"] | None:
        return self._interrupt_action


def init_active_samples() -> None:
    _active_samples.clear()


@contextlib.asynccontextmanager
async def active_sample(
    *,
    task: str,
    log_location: str,
    model: str,
    sample: Sample,
    epoch: int,
    message_limit: int | None,
    token_limit: int | None,
    time_limit: int | None,
    working_limit: int | None,
    fails_on_error: bool,
    transcript: Transcript,
    tg: TaskGroup,
) -> AsyncGenerator[ActiveSample, None]:
    # create the sample
    active = ActiveSample(
        task=task,
        log_location=log_location,
        model=model,
        sample=sample,
        epoch=epoch,
        message_limit=message_limit,
        token_limit=token_limit,
        time_limit=time_limit,
        working_limit=working_limit,
        sandboxes=await sandbox_connections(),
        fails_on_error=fails_on_error,
        transcript=transcript,
        tg=tg,
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


def active_sample_message_limit() -> int | None:
    active = sample_active()
    if active:
        return active.message_limit
    else:
        return None


def set_active_sample_message_limit(message_limit: int | None) -> None:
    active = sample_active()
    if active:
        active.message_limit = message_limit


def set_active_sample_total_messages(total_messages: int) -> None:
    active = sample_active()
    if active:
        active.total_messages = total_messages


_active_model_event: ContextVar[ModelEvent | None] = ContextVar(
    "_active_model_event", default=None
)


@contextlib.contextmanager
def track_active_model_event(event: ModelEvent) -> Iterator[None]:
    token = _active_model_event.set(event)
    try:
        yield
    finally:
        _active_model_event.reset(token)


def report_active_sample_retry() -> None:
    model_event = _active_model_event.get()
    if model_event is not None:
        if model_event.retries is None:
            model_event.retries = 0
        model_event.retries = model_event.retries + 1


_sample_active: ContextVar[ActiveSample | None] = ContextVar(
    "_sample_active", default=None
)


def active_samples() -> list[ActiveSample]:
    return _active_samples


_active_samples: list[ActiveSample] = []
