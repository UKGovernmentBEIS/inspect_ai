import abc
from typing import Literal

from inspect_ai._util.error import EvalError
from inspect_ai.log._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
)


class Recorder(abc.ABC):
    @abc.abstractmethod
    def is_local(self) -> bool: ...

    @abc.abstractmethod
    def log_init(self, eval: EvalSpec) -> str: ...

    @abc.abstractmethod
    def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None: ...

    @abc.abstractmethod
    def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None: ...

    @abc.abstractmethod
    def flush(self, eval: EvalSpec) -> None: ...

    @abc.abstractmethod
    def log_finish(
        self,
        eval: EvalSpec,
        status: Literal["success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        error: EvalError | None = None,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    def handles_location(cls, ocation: str) -> bool: ...

    @classmethod
    @abc.abstractmethod
    def read_log(cls, location: str, header_only: bool = False) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    def write_log(cls, location: str, log: EvalLog) -> None: ...
