import abc
from typing import IO

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.error import EvalError
from inspect_ai.log._log import (
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalSpec,
    EvalStats,
    EvalStatus,
)


class Recorder(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def handles_location(cls, location: str) -> bool: ...

    @classmethod
    @abc.abstractmethod
    def handles_bytes(cls, first_bytes: bytes) -> bool: ...

    @abc.abstractmethod
    def default_log_buffer(self, sample_count: int) -> int: ...

    @abc.abstractmethod
    def is_writeable(self) -> bool: ...

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
        status: EvalStatus,
        stats: EvalStats,
        results: EvalResults | None,
        reductions: list[EvalSampleReductions] | None,
        error: EvalError | None = None,
        header_only: bool = False,
        invalidated: bool = False,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log(
        cls,
        location: str,
        header_only: bool = False,
        async_fs: AsyncFilesystem | None = None,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_bytes(
        cls, log_bytes: IO[bytes], header_only: bool = False
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_sample(
        cls,
        location: str,
        id: str | int | None = None,
        epoch: int = 1,
        uuid: str | None = None,
        exclude_fields: set[str] | None = None,
    ) -> EvalSample: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_sample_summaries(
        cls, location: str, async_fs: AsyncFilesystem | None = None
    ) -> list[EvalSampleSummary]: ...

    @classmethod
    async def read_log_sample_ids(cls, location: str) -> list[tuple[str | int, int]]:
        return sorted(
            (
                (sample_summary.id, sample_summary.epoch)
                for sample_summary in await cls.read_log_sample_summaries(location)
            ),
            key=lambda x: (
                x[1],
                (x[0] if isinstance(x[0], str) else str(x[0]).zfill(20)),
            ),
        )

    @classmethod
    @abc.abstractmethod
    async def write_log(
        cls, location: str, log: EvalLog, if_match_etag: str | None = None
    ) -> None: ...
