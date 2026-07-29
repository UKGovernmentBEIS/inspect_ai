import abc
from typing import IO, TYPE_CHECKING

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.error import EvalError
from inspect_ai.log._config_update import ConfigUpdate
from inspect_ai.log._edit import LogUpdate
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
from inspect_ai.log._recorders.streaming import materialize_streaming_sample

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.history import SampleHistory


class Recorder(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def handles_location(cls, location: str) -> bool: ...

    @classmethod
    @abc.abstractmethod
    def handles_bytes(cls, first_bytes: bytes) -> bool: ...

    @abc.abstractmethod
    def default_log_buffer(self, sample_count: int, high_throughput: bool) -> int: ...

    @abc.abstractmethod
    def is_writeable(self) -> bool: ...

    @abc.abstractmethod
    async def log_init(self, eval: EvalSpec, location: str | None = None) -> str: ...

    @abc.abstractmethod
    async def log_start(self, eval: EvalSpec, plan: EvalPlan) -> None: ...

    @abc.abstractmethod
    async def log_sample(self, eval: EvalSpec, sample: EvalSample) -> None: ...

    async def log_sample_streaming(
        self, eval: EvalSpec, sample: EvalSample, history: "SampleHistory"
    ) -> None:
        await self.log_sample(eval, materialize_streaming_sample(sample, history))

    async def sample_summaries(self, eval: EvalSpec) -> list[EvalSampleSummary] | None:
        """Live per-sample summaries for an in-progress eval, if available.

        Returns the recorder's in-memory record of every sample logged so
        far (i.e. completed samples) — gap-free and ahead of what's been
        flushed to disk. Used by the control channel to list an eval's
        samples while it runs. Returns ``None`` when the recorder can't
        serve them in-memory (eg. the eval has finished and been torn
        down, or this recorder type doesn't retain summaries); callers
        then fall back to reading the on-disk log.
        """
        return None

    async def buffered_sample(
        self, eval: EvalSpec, id: str | int, epoch: int
    ) -> EvalSample | None:
        """The full ``EvalSample`` for one sample, if held in-memory.

        Counterpart to :meth:`sample_summaries` for whole samples: returns the
        recorder's not-yet-flushed in-memory ``EvalSample`` (carrying the full
        ``error_retries`` / ``events`` / ``scores`` a summary omits) — gap-free
        and ahead of disk, so a just-completed sample is readable before it's
        flushed. Returns ``None`` when the recorder can't serve it in-memory
        (already flushed, eval torn down, or this recorder type doesn't buffer
        whole samples); callers then read the on-disk log.
        """
        return None

    async def log_config_update(self, eval: EvalSpec, update: ConfigUpdate) -> None:
        """Record a mid-run config change (see ``EvalLog.config_updates``).

        Called while the eval runs, when a `inspect ctl config` retune is
        applied. The base implementation is a no-op so recorder subclasses
        that don't persist mid-run state keep working; the built-in
        recorders override it to journal the update (`.eval`) or accumulate
        it in the in-memory log (JSON) so it lands in the finished header.
        """

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
        log_updates: list[LogUpdate] | None = None,
        config_updates: list[ConfigUpdate] | None = None,
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log(
        cls,
        location: str,
        header_only: bool = False,
        exclude_fields: set[str] | None = None,
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
        reader: AsyncZipReader | None = None,
    ) -> EvalSample: ...

    @classmethod
    @abc.abstractmethod
    async def read_log_sample_summaries(
        cls, location: str
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
        cls,
        location: str,
        log: EvalLog,
        if_match_etag: str | None = None,
        header_only: bool = False,
    ) -> None: ...
