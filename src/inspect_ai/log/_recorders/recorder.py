import abc
from functools import lru_cache
from typing import IO, TYPE_CHECKING

from pydantic import TypeAdapter

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.error import EvalError
from inspect_ai.event import Event
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
from inspect_ai.log._pool import resolve_sample_events_data

if TYPE_CHECKING:
    from inspect_ai.log._event_store.history import SampleHistory


@lru_cache(maxsize=1)
def _events_adapter() -> TypeAdapter[list[Event]]:
    return TypeAdapter(list[Event])


def materialize_streaming_events(events: list[object]) -> list[Event]:
    return _events_adapter().validate_python(
        events, context=get_deserializing_context()
    )


def materialize_streaming_sample(
    sample: EvalSample, history: "SampleHistory"
) -> EvalSample:
    events = materialize_streaming_events(list(history.event_dicts()))
    materialized = resolve_sample_events_data(
        sample.model_copy(update={"events": events, "events_data": history.events_data})
    )
    return materialized.model_copy(
        update={
            "attachments": {
                **materialized.attachments,
                **history.attachments,
            }
        }
    )


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
    ) -> EvalLog: ...

    @classmethod
    @abc.abstractmethod
    async def read_log(
        cls,
        location: str,
        header_only: bool = False,
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
