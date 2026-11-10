import contextlib
from dataclasses import dataclass, field
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Coroutine,
    Iterator,
    Literal,
    Protocol,
    Type,
    TypeVar,
    Union,
    runtime_checkable,
)

import anyio
import rich
from pydantic import BaseModel, Field, field_validator
from rich.console import Console

from inspect_ai.log import EvalConfig, EvalResults, EvalStats
from inspect_ai.model import GenerateConfig, ModelName

from ...util._panel import InputPanel


@runtime_checkable
class Progress(Protocol):
    def update(self, n: int = 1) -> None: ...

    def complete(self) -> None: ...


@dataclass
class TaskSpec:
    name: str
    model: ModelName
    agent: str | None


CancelType = Literal["abort", "retry", "score", "error", "drain"] | None
"""How a task cancel resolves.

``abort`` and ``retry`` tear the task's cancel scope down (the classic
user-cancel paths). ``score`` and ``error`` are graceful sample resolutions:
the scope is left alone — in-flight samples are interrupted with the matching
``ActiveSample.interrupt`` action, queued samples are abandoned, and the task
runs to natural completion (see ``inspect_ai._control.cancel.cancel_task``).
``drain`` is that machinery minus the interrupt sweep: queued samples abandon
as they leave the queue, in-flight samples are never touched and finish
naturally, and the task completes when the last one does (see
``inspect_ai._control.cancel.drain_task`` and ``design/ctl/task-drain.md``).
"""


# The escalation ladder, ordered by invasiveness: a request strictly stronger
# than the stamp replaces it; anything equal or weaker is a no-op, so no caller
# can lower or clear a stamp. Score and error are unordered peers. Abort
# outranks retry so a retry chosen in the cancel dialog cannot re-run a task an
# operator cancelled. See design/ctl/task-drain.md "Escalation ladder and
# idempotence" (teardown must always remain reachable, e.g. a draining task
# stalled on a hung sample, and score/error is drain's "stop waiting" relief
# valve).
_ESCALATION_LADDER: dict[str, int] = {
    "drain": 0,
    "score": 1,
    "error": 1,
    "retry": 2,
    "abort": 3,
}


@dataclass
class TaskCancel:
    """A task attempt's cancel stamp, changed only through :meth:`request`.

    The stamp only escalates (see ``_ESCALATION_LADDER``). Once the attempt's
    cancel scope has exited (:meth:`close`) its outcome is decided, and only an
    abort of an attempt that ended in error is still accepted: it stops the
    dispatcher from retrying it.
    """

    can_retry: bool
    apply: Callable[[CancelType], None]
    """Carries out a stamp: wakes pause waiters; abort and retry cancel the
    task's scope (or, during the error-log write, take effect when it ends)."""
    log_write_scope: anyio.CancelScope | None = None
    """The scope around the task's error-log write while it runs. An abort or
    retry request made then bounds the write and takes effect when it ends
    (see ``abort_bounded_write``)."""
    _cancel_type: CancelType = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)
    _ended_in_error: bool = field(default=False, init=False)

    @property
    def cancel_type(self) -> CancelType:
        """How the attempt was asked to cancel (``None`` if it was not)."""
        return self._cancel_type

    def escalates(self, requested: CancelType) -> bool:
        """Whether :meth:`request` would accept ``requested``."""
        if requested is None:
            return False
        if self._closed and not (requested == "abort" and self._ended_in_error):
            return False
        return (
            self._cancel_type is None
            or _ESCALATION_LADDER[requested] > _ESCALATION_LADDER[self._cancel_type]
        )

    def request(self, requested: CancelType) -> None:
        """Stamp and apply ``requested`` if it escalates; otherwise do nothing."""
        if self.escalates(requested):
            self._cancel_type = requested
            self.apply(requested)

    def close(self, ended_in_error: bool) -> None:
        """Record that the attempt's cancel scope has exited."""
        self._closed = True
        self._ended_in_error = ended_in_error


@dataclass
class TaskProfile:
    name: str
    file: str | None
    model: ModelName
    agent: str | None
    dataset: str
    scorer: str
    samples: int
    steps: int
    eval_config: EvalConfig
    task_args: dict[str, Any]
    generate_config: GenerateConfig
    tags: list[str] | None
    log_location: str
    task_id: str
    task_cancel: TaskCancel | None


@dataclass
class TaskError:
    samples_completed: int
    exc_type: Type[Any]
    exc_value: BaseException
    traceback: TracebackType | None


@dataclass
class TaskCancelled:
    samples_completed: int
    stats: EvalStats


@dataclass
class TaskSuccess:
    samples_completed: int
    stats: EvalStats
    results: EvalResults


TaskResult = Union[TaskError, TaskCancelled, TaskSuccess]


@dataclass
class TaskWithResult:
    profile: TaskProfile
    result: TaskResult | None


TR = TypeVar("TR")

TP = TypeVar("TP", bound=InputPanel)


class TaskScreen(contextlib.AbstractContextManager["TaskScreen"]):
    def __exit__(self, *excinfo: Any) -> None:
        pass

    @contextlib.contextmanager
    def input_screen(
        self,
        header: str | None = None,
        transient: bool | None = None,
        width: int | None = None,
        record_event: bool = True,
    ) -> Iterator[Console]:
        yield rich.get_console()

    async def input_panel(self, panel_type: type[TP]) -> TP:
        raise NotImplementedError("input_panel not implemented by current display")


class TaskDisplayMetric(BaseModel):
    scorer: str
    """`EvalScore.name` — for a dict-valued scorer this is one of its value
    keys rather than the scorer's own name."""

    scorer_name: str | None = Field(default=None)
    """`EvalScore.scorer` — tells apart two dict-valued scorers sharing a key."""

    headline: bool = Field(default=False)
    """Whether this is the eval's headline metric. Marked here because the
    display shape drops the identity a headline reference matches on."""

    name: str
    value: float | int | None = Field(default=None)
    reducer: str | None = Field(default=None)
    params: dict[str, Any] | None = Field(default=None)

    @field_validator("value", mode="before")
    @classmethod
    def handle_null_value(cls, v: Any) -> Union[float, int, None]:
        if v is None:
            return None
        if isinstance(v, float | int):
            return v
        raise ValueError(f"Expected float, int, or None, got {type(v)}")


@runtime_checkable
class TaskDisplay(Protocol):
    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]: ...

    def sample_complete(self, complete: int, total: int) -> None: ...

    def update_metrics(self, scores: list[TaskDisplayMetric]) -> None: ...

    def complete(self, result: TaskResult) -> None: ...


@runtime_checkable
class Display(Protocol):
    def print(self, message: str) -> None: ...

    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]: ...

    def run_task_app(self, main: Callable[[], Coroutine[None, None, TR]]) -> TR: ...

    @contextlib.contextmanager
    def suspend_task_app(self) -> Iterator[None]: ...

    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        yield TaskScreen()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]: ...

    def display_counter(self, caption: str, value: str) -> None: ...

    def update_task_count(self, n: int) -> None:
        """Add ``n`` to the displayed total task count.

        Called when tasks are injected into a live (TaskSource-driven) run so
        the "completed / total" denominator reflects the growing set. No-op by
        default; displays that show a total override this.
        """
        return None
