"""Sample working time: wall-clock time minus the union of known waits.

At each instant a sample is waiting if at least one known wait is open
anywhere in the sample, and working otherwise. Waits are merged, never
added, so working time always lies between zero and the elapsed time. See
design/working-time-concurrency.md.
"""

import contextlib
import time
from bisect import bisect_left, bisect_right
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterator


@dataclass
class SampleTiming:
    """Working-time state for one attempt of a sample.

    Keeps the merged set of closed wait intervals for the whole attempt plus
    a count of open waits. While any wait is open, the live span runs from
    the start of the oldest open wait to now.
    """

    start_time: float = 0.0
    """Start of this attempt on `clock`."""

    start_datetime: datetime | None = None

    clock: Callable[[], float] = time.monotonic
    """The sample clock (tests inject a fake one)."""

    prior_wall: float = 0.0
    """Wall-clock time of prior attempts (restored from a checkpoint)."""

    prior_working: float = 0.0
    """Working time of prior attempts (restored from a checkpoint)."""

    open_waits: int = 0
    open_start: float | None = None

    # merged, disjoint, sorted closed intervals, with prefix sums of their
    # lengths (`_cum[i]` is the total length of intervals `0..i-1`)
    _starts: list[float] = field(default_factory=list)
    _ends: list[float] = field(default_factory=list)
    _cum: list[float] = field(default_factory=list)

    def now(self) -> float:
        return self.clock()

    def open_wait(self) -> None:
        if self.open_waits == 0:
            self.open_start = self.now()
        self.open_waits += 1

    def close_wait(self) -> None:
        self.open_waits -= 1
        if self.open_waits == 0 and self.open_start is not None:
            start = self.open_start
            self.open_start = None
            self.add_wait(start, self.now())

    def add_wait(self, start: float, end: float) -> None:
        """Merge the closed interval `[start, end]`, clipped to this attempt."""
        start = max(start, self.start_time)
        end = min(end, self.now())
        if end <= start:
            return
        # intervals that overlap or touch [start, end]
        i = bisect_left(self._ends, start)
        j = bisect_right(self._starts, end)
        if i < j:
            start = min(start, self._starts[i])
            end = max(end, self._ends[j - 1])
        self._starts[i:j] = [start]
        self._ends[i:j] = [end]
        self._cum[i:j] = [0.0]
        total = self._cum[i - 1] + self._ends[i - 1] - self._starts[i - 1] if i else 0.0
        for k in range(i, len(self._starts)):
            self._cum[k] = total
            total += self._ends[k] - self._starts[k]

    def waiting(self, a: float, b: float) -> float:
        """Length of `[a, b]` covered by any known wait (closed or open)."""
        b = min(b, self.now())
        if b <= a:
            return 0.0
        waiting = self._closed(a, b)
        if self.open_start is not None:
            lo = max(a, self.open_start)
            if b > lo:
                # the live span counts once where it overlaps closed waits
                waiting += (b - lo) - self._closed(lo, b)
        # bound float rounding in the prefix sums
        return min(max(waiting, 0.0), b - a)

    def elapsed(self) -> float:
        """Wall-clock time of this attempt so far."""
        return self.now() - self.start_time

    def working(self) -> float:
        """Working time of this attempt so far."""
        now = self.now()
        return (now - self.start_time) - self.waiting(self.start_time, now)

    def _closed(self, a: float, b: float) -> float:
        return self._closed_before(b) - self._closed_before(a)

    def _closed_before(self, x: float) -> float:
        """Length of the closed waits that lie before `x`."""
        i = bisect_right(self._starts, x) - 1
        if i < 0:
            return 0.0
        return self._cum[i] + min(x, self._ends[i]) - self._starts[i]


def init_sample_working_time(
    start_time: float, clock: Callable[[], float] = time.monotonic
) -> None:
    _sample_timing.set(
        SampleTiming(
            start_time=start_time,
            start_datetime=datetime.now(timezone.utc),
            clock=clock,
        )
    )


def sample_timing() -> SampleTiming | None:
    """Working-time state of the running sample (`None` outside a sample)."""
    return _sample_timing.get()


def sample_clock() -> float:
    """Current time on the sample clock (`time.monotonic()` outside a sample)."""
    timing = _sample_timing.get()
    return timing.now() if timing is not None else time.monotonic()


def sample_waiting_time(start: float | None = None, end: float | None = None) -> float:
    """Waiting time of this attempt within `[start, end]` on the sample clock.

    Args:
       start: Start of the window (defaults to the start of the attempt).
       end: End of the window (defaults to now).
    """
    timing = _sample_timing.get()
    if timing is None:
        return 0.0
    return timing.waiting(
        start if start is not None else timing.start_time,
        end if end is not None else timing.now(),
    )


def sample_working_time() -> float:
    """Working time of the sample, including prior attempts."""
    timing = _sample_timing.get()
    if timing is None:
        return time.monotonic()
    return timing.prior_working + timing.working()


def sample_start_datetime() -> datetime | None:
    timing = _sample_timing.get()
    return timing.start_datetime if timing is not None else None


def report_sample_waiting_time(waiting_time: float) -> None:
    """Record that the sample was waiting for the last `waiting_time` seconds.

    Adds the interval `[now - waiting_time, now]` to the sample's known waits,
    merged with the waits already known.
    """
    timing = _sample_timing.get()
    if timing is not None:
        now = timing.now()
        timing.add_wait(now - waiting_time, now)


def add_sample_wait(start: float, end: float) -> None:
    """Record the closed interval `[start, end]` (sample clock) as a known wait."""
    timing = _sample_timing.get()
    if timing is not None:
        timing.add_wait(start, end)


class SampleWait:
    """A known wait that stays open until `close()` (idempotent).

    Bound to the sample whose context opened it, so another task may close it.
    """

    def __init__(self) -> None:
        self._timing = _sample_timing.get()
        if self._timing is not None:
            self._timing.open_wait()

    def close(self) -> None:
        if self._timing is not None:
            timing, self._timing = self._timing, None
            timing.close_wait()


@contextlib.contextmanager
def sample_wait() -> Iterator[None]:
    """Mark the sample as waiting while the block runs (no-op outside a sample)."""
    wait = SampleWait()
    try:
        yield
    finally:
        wait.close()


_sample_timing: ContextVar[SampleTiming | None] = ContextVar(
    "sample_timing", default=None
)


@contextlib.asynccontextmanager
async def sample_waiting_for(
    semaphore: contextlib.AbstractAsyncContextManager[Any],
) -> AsyncIterator[None]:
    """Acquire a semaphore, counting the time spent acquiring it as waiting.

    Args:
        semaphore: The semaphore to acquire (as an async context manager)
    """
    wait = SampleWait()
    try:
        async with semaphore:
            wait.close()
            yield
    finally:
        wait.close()
