import contextlib
import time
from bisect import bisect_left
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator


class WaitingTime:
    """Union of completed and ongoing waits on the monotonic clock."""

    def __init__(self) -> None:
        self._spans: list[tuple[float, float]] = []
        self._active: list[float] = []
        self._total = 0.0

    def record(self, start: float, end: float) -> None:
        if end <= start:
            return
        first = bisect_left(self._spans, (start, end))
        if first and self._spans[first - 1][1] >= start:
            first -= 1
        last = first
        while last < len(self._spans) and self._spans[last][0] <= end:
            previous_start, previous_end = self._spans[last]
            start, end = min(start, previous_start), max(end, previous_end)
            self._total -= previous_end - previous_start
            last += 1
        self._spans[first:last] = [(start, end)]
        self._total += end - start

    def elapsed(self, now: float | None = None) -> float:
        if not self._active:
            return self._total
        start = min(self._active)
        end = time.monotonic() if now is None else now
        first = max(0, bisect_left(self._spans, (start, start)) - 1)
        overlap = sum(
            max(0.0, min(previous_end, end) - max(previous_start, start))
            for previous_start, previous_end in self._spans[first:]
        )
        return self._total + end - start - overlap

    @contextlib.contextmanager
    def track(self) -> Iterator[None]:
        start = time.monotonic()
        self._active.append(start)
        try:
            yield
        finally:
            self._active.remove(start)
            self.record(start, time.monotonic())


@dataclass
class SampleTiming:
    start_time: float = 0.0
    waiting: WaitingTime = field(default_factory=WaitingTime)
    start_datetime: datetime | None = None


def init_sample_working_time(start_time: float) -> None:
    _sample_timing.set(
        SampleTiming(
            start_time=start_time,
            start_datetime=datetime.now(timezone.utc),
        )
    )


def sample_waiting_time() -> float:
    return _sample_timing.get().waiting.elapsed()


def sample_working_time() -> float:
    timing = _sample_timing.get()
    now = time.monotonic()
    return now - timing.start_time - timing.waiting.elapsed(now)


def sample_start_datetime() -> datetime | None:
    return _sample_timing.get().start_datetime


def report_sample_waiting_time(
    waiting_time: float, start_time: float | None = None
) -> None:
    if waiting_time <= 0:
        return
    start = time.monotonic() - waiting_time if start_time is None else start_time
    for waiting in _waiting_times():
        waiting.record(start, start + waiting_time)


def _waiting_times() -> Iterator[WaitingTime]:
    from inspect_ai.util._limit import working_limit_tree

    timing = _sample_timing.get()
    if timing.start_datetime is not None:
        yield timing.waiting
    node = working_limit_tree.get()
    while node is not None:
        yield node._waits
        node = node.parent


_sample_timing: ContextVar[SampleTiming] = ContextVar(
    "sample_timing", default=SampleTiming()
)


@contextlib.asynccontextmanager
async def sample_waiting() -> AsyncIterator[None]:
    """Track a waiting span without owning a semaphore hold.

    The acquire-only counterpart to :func:`sample_waiting_for`: wraps just
    the wait (the caller keeps whatever it acquired), with the same
    concurrent-wait dedup so overlapping waits within one sample aren't
    double-counted.
    """
    with contextlib.ExitStack() as stack:
        for waiting in _waiting_times():
            stack.enter_context(waiting.track())
        yield


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
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(sample_waiting())
        async with semaphore:
            await stack.aclose()
            yield
