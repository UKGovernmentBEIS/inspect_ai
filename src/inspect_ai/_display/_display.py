import abc
import contextlib
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Iterator, Type

from inspect_ai.log import EvalConfig, EvalError, EvalResults, EvalStats
from inspect_ai.model import GenerateConfig, ModelName


class Progress(abc.ABC):
    @abc.abstractmethod
    def update(self, n: float = 1) -> None: ...


class TaskDisplay(abc.ABC):
    @abc.abstractmethod
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]: ...

    @abc.abstractmethod
    def cancelled(self, samples_logged: int, stats: EvalStats) -> None: ...

    @abc.abstractmethod
    def summary(self, results: EvalResults, stats: EvalStats) -> None: ...

    @abc.abstractmethod
    def error(
        self,
        samples_logged: int,
        error: EvalError,
        exc_type: Type[Any],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None: ...


@dataclass
class TaskProfile:
    name: str
    sequence: tuple[int, int]
    model: ModelName
    dataset: str
    scorer: str
    samples: int
    eval_config: EvalConfig
    task_args: dict[str, Any]
    generate_config: GenerateConfig
    log_location: str


class Display(abc.ABC):
    @abc.abstractmethod
    def print(self, message: str) -> None: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]: ...

    @abc.abstractmethod
    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]: ...
