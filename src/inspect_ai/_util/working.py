import time
from contextvars import ContextVar
from dataclasses import dataclass

from inspect_ai.util._limit import record_waiting_time


@dataclass
class SampleTiming:
    start_time: float = 0.0
    waiting_time: float = 0.0


def init_sample_working_time(start_time: float) -> None:
    _sample_timing.set(SampleTiming(start_time=start_time))


def sample_waiting_time() -> float:
    return _sample_timing.get().waiting_time


def sample_working_time() -> float:
    timing = _sample_timing.get()
    return time.monotonic() - timing.start_time - timing.waiting_time


def report_sample_waiting_time(waiting_time: float) -> None:
    # record waiting time
    record_waiting_time(waiting_time)

    # record sample-level limits
    _sample_timing.get().waiting_time = _sample_timing.get().waiting_time + waiting_time


_sample_timing: ContextVar[SampleTiming] = ContextVar(
    "sample_timing", default=SampleTiming()
)
