import abc
import contextlib
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Iterator, Type, Union

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
    model: ModelName
    dataset: str
    scorer: str
    samples: int
    steps: int
    eval_config: EvalConfig
    task_args: dict[str, Any]
    generate_config: GenerateConfig
    log_location: str


@dataclass
class TaskError:
    samples_logged: int
    exc_type: Type[Any]
    exc_value: BaseException
    traceback: TracebackType | None


@dataclass
class TaskCancelled:
    samples_logged: int
    stats: EvalStats


@dataclass
class TaskSuccess:
    stats: EvalStats
    results: EvalResults


TaskResult = Union[TaskError, TaskCancelled, TaskSuccess]


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
    def live_task_status(self) -> Iterator[None]: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]: ...
