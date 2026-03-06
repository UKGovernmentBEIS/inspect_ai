import contextlib
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator


@dataclass
class SampleTiming:
    start_time: float = 0.0
    waiting_time: float = 0.0
    start_datetime: datetime | None = None
    # Track concurrent waiting to avoid double-counting overlapping waits
    concurrent_wait_count: int = 0
    concurrent_wait_start: float | None = None


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


@contextlib.asynccontextmanager
async def sample_waiting_for(
    semaphore: contextlib.AbstractAsyncContextManager[Any],
) -> AsyncIterator[None]:
    """Acquire a semaphore while tracking sample waiting time.

    This context manager wraps semaphore acquisition and ensures that
    concurrent waits within the same sample are not double-counted.
    Only wall-clock time when at least one task is waiting is reported.

    Args:
        semaphore: The semaphore to acquire (as an async context manager)
    """
    timing = _sample_timing.get()

    # Start waiting - record start time if we're the first waiter
    if timing.concurrent_wait_count == 0:
        timing.concurrent_wait_start = time.monotonic()
    timing.concurrent_wait_count += 1

    acquired = False
    try:
        async with semaphore:
            acquired = True
            _end_sample_wait()
            yield
    finally:
        if not acquired:
            _end_sample_wait()


def _end_sample_wait() -> None:
    """Internal: decrement wait count and report time if this was the last waiter."""
    timing = _sample_timing.get()
    timing.concurrent_wait_count -= 1
    if timing.concurrent_wait_count == 0 and timing.concurrent_wait_start is not None:
        waiting_time = time.monotonic() - timing.concurrent_wait_start
        timing.concurrent_wait_start = None
        report_sample_waiting_time(waiting_time)
