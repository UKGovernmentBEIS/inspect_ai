import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SampleTiming:
    start_time: float = 0.0
    waiting_time: float = 0.0
    start_datetime: datetime | None = None


def init_sample_working_time(start_time: float) -> None:
    _sample_timing.set(
        SampleTiming(
            start_time=start_time,
            start_datetime=datetime.now(timezone.utc),
        )
    )


def sample_waiting_time() -> float:
    return _sample_timing.get().waiting_time


def sample_working_time() -> float:
    timing = _sample_timing.get()
    return time.monotonic() - timing.start_time - timing.waiting_time


def sample_start_datetime() -> datetime | None:
    return _sample_timing.get().start_datetime


def report_sample_waiting_time(waiting_time: float) -> None:
    # record waiting time
    from inspect_ai.util._limit import record_waiting_time

    record_waiting_time(waiting_time)

    # record sample-level limits
    _sample_timing.get().waiting_time = _sample_timing.get().waiting_time + waiting_time


_sample_timing: ContextVar[SampleTiming] = ContextVar(
    "sample_timing", default=SampleTiming()
)
