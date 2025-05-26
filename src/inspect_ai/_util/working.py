import time
from contextvars import ContextVar

from inspect_ai.util._limit import check_working_limit, record_waiting_time


def init_sample_working_time(start_time: float) -> None:
    _sample_start_time.set(start_time)
    _sample_waiting_time.set(0)


def sample_waiting_time() -> float:
    return _sample_waiting_time.get()


def sample_working_time() -> float:
    return time.monotonic() - _sample_start_time.get() - sample_waiting_time()


def report_sample_waiting_time(waiting_time: float) -> None:
    # record and check for scoped limits
    record_waiting_time(waiting_time)
    check_working_limit()

    # record sample-level limits
    _sample_waiting_time.set(_sample_waiting_time.get() + waiting_time)


_sample_start_time: ContextVar[float] = ContextVar("sample_start_time", default=0)

_sample_waiting_time: ContextVar[float] = ContextVar("sample_waiting_time", default=0)
