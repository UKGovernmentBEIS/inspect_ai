import abc
import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Iterator, Type, Union

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


class TaskScreen(contextlib.AbstractContextManager["TaskScreen"]):
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
    @contextlib.contextmanager
    def task_screen(self, total_tasks: int, parallel: bool) -> Iterator[TaskScreen]: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]: ...


def task_screen() -> TaskScreen:
    screen = _task_screen.get(None)
    if screen is None:
        raise RuntimeError(
            "console input function called outside of running evaluation."
        )
    return screen


def init_task_screen(screen: TaskScreen) -> None:
    _task_screen.set(screen)


def clear_task_screen() -> None:
    _task_screen.set(None)


_task_screen: ContextVar[TaskScreen | None] = ContextVar("task_screen", default=None)
