import contextlib
from dataclasses import dataclass
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Coroutine,
    Iterator,
    Protocol,
    Type,
    TypeVar,
    Union,
    runtime_checkable,
)

import rich
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


@dataclass
class TaskProfile:
    name: str
    file: str | None
    model: ModelName
    dataset: str
    scorer: str
    samples: int
    steps: int
    eval_config: EvalConfig
    task_args: dict[str, Any]
    generate_config: GenerateConfig
    tags: list[str] | None
    log_location: str


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
    ) -> Iterator[Console]:
        yield rich.get_console()

    async def input_panel(self, title: str, panel: type[TP]) -> TP:
        raise NotImplementedError("input_panel not implemented by current display")


@dataclass
class TaskDisplayMetric:
    scorer: str
    name: str
    value: float | int
    reducer: str | None


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

    def run_task_app(self, main: Coroutine[Any, Any, TR]) -> TR: ...

    @contextlib.contextmanager
    def suspend_task_app(self) -> Iterator[None]: ...

    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        yield TaskScreen()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]: ...
