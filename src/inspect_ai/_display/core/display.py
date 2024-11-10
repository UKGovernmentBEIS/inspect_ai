import abc
import contextlib
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Coroutine, Iterator, Type, TypeVar, Union

from rich.console import Console

from inspect_ai.log import EvalConfig, EvalResults, EvalStats
from inspect_ai.model import GenerateConfig, ModelName


class Progress(abc.ABC):
    @abc.abstractmethod
    def update(self, n: int = 1) -> None: ...

    @abc.abstractmethod
    def complete(self) -> None: ...


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


class TaskScreen:
    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    def cancel_on_exit(self) -> bool:
        return False

    @abc.abstractmethod
    @contextlib.contextmanager
    def input_screen(
        self,
        header: str | None = None,
        transient: bool | None = None,
        width: int | None = None,
    ) -> Iterator[Console]: ...


class TaskDisplay(abc.ABC):
    @abc.abstractmethod
    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]: ...

    @abc.abstractmethod
    def complete(self, result: TaskResult) -> None: ...


class Display(abc.ABC):
    @abc.abstractmethod
    def print(self, message: str) -> None: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]: ...

    @abc.abstractmethod
    def run_task_app(self, title: str, main: Coroutine[Any, Any, TR]) -> TR: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def task_screen(self, total_tasks: int, parallel: bool) -> Iterator[TaskScreen]: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]: ...
