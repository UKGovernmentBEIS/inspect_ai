import abc
from typing import Literal

from inspect_ai._util.error import EvalError
from inspect_ai.log._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSpec,
    EvalStats,
)


class Recorder(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def handles_location(cls, location: str) -> bool: ...

    @abc.abstractmethod
    def default_log_buffer(self) -> int: ...

    @abc.abstractmethod
    async def log_init(self, eval: EvalSpec, location: str | None = None) -> str: ...

    @abc.abstractmethod
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None: ...

    @abc.abstractmethod
    async def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None: ...

    @abc.abstractmethod
    async def flush(self, eval: EvalSpec) -> None: ...

    @abc.abstractmethod
    async def log_finish(
        self,
        eval: EvalSpec,
        status: Literal["success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log(cls, location: str, header_only: bool = False) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_sample(
        cls, location: str, id: str | int, epoch: int = 1
    ) -> EvalSample: ...

    @classmethod
    @abc.abstractmethod
    async def write_log(cls, location: str, log: EvalLog) -> None: ...
