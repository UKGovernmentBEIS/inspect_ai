import contextlib
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator, Iterator, Literal

if TYPE_CHECKING:
    from inspect_ai.model._model_call import ModelCall, ModelCallFilter

from anyio.abc import TaskGroup
from shortuuid import uuid

from inspect_ai.dataset._dataset import Sample
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox import SandboxConnection
from inspect_ai.util._sandbox.context import sandbox_connections

from ..event._model import ModelEvent
from ._transcript import Transcript


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
        cost_limit: float | None,
        time_limit: int | None,
        working_limit: int | None,
        fails_on_error: bool,
        transcript: Transcript,
        sandboxes: dict[str, SandboxConnection],
    ) -> None:
        self.id = uuid()
        self.started: float | None = None
        self.tg: TaskGroup | None = None
        self.completed: float | None = None
        self.task = task
        self.log_location = log_location
        self.model = model
        self.sample = sample
        self.epoch = epoch
        self.message_limit = message_limit
        self.token_limit = token_limit
        self.cost_limit = cost_limit
        self.time_limit = time_limit
        self.working_limit = working_limit
        self.fails_on_error = fails_on_error
        self.total_messages = 0
        self.total_tokens = 0
        self.total_cost: float | None = None
        self.transcript = transcript
        self.sandboxes = sandboxes
        self._interrupt_action: Literal["score", "error"] | None = None
        self._limit_exceeded_error: LimitExceededError | None = None

    def start(self, tg: TaskGroup) -> None:
        self.started = datetime.now(timezone.utc).timestamp()
        self.tg = tg

    def complete(self) -> None:
        self.completed = datetime.now(timezone.utc).timestamp()

    @property
    def running_time(self) -> float:
        if self.started is not None:
            completed = (
                self.completed
                if self.completed is not None
                else datetime.now(timezone.utc).timestamp()
            )
            return completed - self.started
        else:
            return 0

    def interrupt(self, action: Literal["score", "error"]) -> None:
        self._interrupt_action = action
        if self.tg is None:
            raise RuntimeError(
                "Attempted to interrupt sample without enclosing task group."
            )
        self.tg.cancel_scope.cancel()

    def limit_exceeded(self, error: LimitExceededError) -> None:
        self._limit_exceeded_error = error
        if self.tg is None:
            raise RuntimeError(
                "Attempted to interrupt sample for limit without enclosing task group."
            )
        self.tg.cancel_scope.cancel()

    @property
    def interrupt_action(self) -> Literal["score", "error"] | None:
        return self._interrupt_action

    @property
    def limit_exceeded_error(self) -> LimitExceededError | None:
        return self._limit_exceeded_error


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
    cost_limit: float | None,
    time_limit: int | None,
    working_limit: int | None,
    fails_on_error: bool,
    transcript: Transcript,
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
        cost_limit=cost_limit,
        time_limit=time_limit,
        working_limit=working_limit,
        sandboxes=await sandbox_connections(),
        fails_on_error=fails_on_error,
        transcript=transcript,
    )

    _active_samples.append(active)
    _sample_active.set(active)
    try:
        yield active
    finally:
        active.complete()
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


def set_active_sample_cost_limit(cost_limit: float | None) -> None:
    active = sample_active()
    if active:
        active.cost_limit = cost_limit


def set_active_sample_total_cost(total_cost: float | None) -> None:
    active = sample_active()
    if active:
        active.total_cost = total_cost


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


def has_active_model_event() -> bool:
    return _active_model_event.get() is not None


def set_active_model_event_call(
    request: Any,
    filter: "ModelCallFilter | None" = None,
) -> "ModelCall":
    """Create a ModelCall and register it with the active model event."""
    from inspect_ai.log._transcript import transcript
    from inspect_ai.model._model_call import ModelCall

    if request is None:
        request = {}
    model_call = ModelCall.create(request, None, filter)
    event = _active_model_event.get()
    if event is not None:
        event.call = model_call
        transcript()._event_updated(event)
    return model_call


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
