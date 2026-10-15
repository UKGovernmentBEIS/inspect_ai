"""Sample working time: wall-clock time minus known waits not covered by known work.

Each instant of a sample is working if any known work is in progress (a model
attempt, a sandbox exec or a tool call that is not itself waiting), otherwise
waiting if any known wait is open anywhere in the sample, and otherwise
working. Waits and work are each merged, never added, so working time always
lies between zero and the elapsed time. See design/working-time-concurrency.md.
"""

import contextlib
import time
from bisect import bisect_left, bisect_right
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterator


class _IntervalSet:
    """Merged, disjoint, sorted closed intervals with prefix sums of lengths."""

    def __init__(self) -> None:
        self._starts: list[float] = []
        self._ends: list[float] = []
        # `_cum[i]` is the total length of intervals `0..i-1`
        self._cum: list[float] = []

    def add(self, start: float, end: float) -> None:
        """Merge `[start, end]` into the set."""
        if end > start:
            self.add_all([(start, end)])

    def add_all(self, intervals: list[tuple[float, float]]) -> None:
        """Merge sorted, disjoint, non-empty intervals into the set."""
        if not intervals:
            return
        # existing intervals that overlap or touch the span of the new ones
        i = bisect_left(self._ends, intervals[0][0])
        j = bisect_right(self._starts, intervals[-1][1])
        merged: list[tuple[float, float]] = []
        for s, e in sorted(
            [(self._starts[k], self._ends[k]) for k in range(i, j)] + intervals
        ):
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        self._splice(i, j, merged)

    def remove(self, start: float, end: float) -> None:
        """Remove `[start, end]` from the set."""
        if end <= start:
            return
        # existing intervals that overlap (start, end)
        i = bisect_right(self._ends, start)
        j = bisect_left(self._starts, end)
        if i >= j:
            return
        kept: list[tuple[float, float]] = []
        if self._starts[i] < start:
            kept.append((self._starts[i], start))
        if self._ends[j - 1] > end:
            kept.append((end, self._ends[j - 1]))
        self._splice(i, j, kept)

    def gaps(self, start: float, end: float) -> list[tuple[float, float]]:
        """The parts of `[start, end]` not covered by the set."""
        gaps: list[tuple[float, float]] = []
        cursor = start
        i = bisect_right(self._ends, start)
        j = bisect_left(self._starts, end)
        for k in range(i, j):
            if self._starts[k] > cursor:
                gaps.append((cursor, self._starts[k]))
            cursor = max(cursor, self._ends[k])
        if cursor < end:
            gaps.append((cursor, end))
        return gaps

    def measure(self, a: float, b: float) -> float:
        """Length of the set within `[a, b]`."""
        return self._before(b) - self._before(a) if b > a else 0.0

    def _before(self, x: float) -> float:
        """Length of the set before `x`."""
        i = bisect_right(self._starts, x) - 1
        if i < 0:
            return 0.0
        return self._cum[i] + min(x, self._ends[i]) - self._starts[i]

    def _splice(self, i: int, j: int, intervals: list[tuple[float, float]]) -> None:
        self._starts[i:j] = [s for s, _ in intervals]
        self._ends[i:j] = [e for _, e in intervals]
        self._cum[i:j] = [0.0] * len(intervals)
        total = self._cum[i - 1] + self._ends[i - 1] - self._starts[i - 1] if i else 0.0
        for k in range(i, len(self._starts)):
            self._cum[k] = total
            total += self._ends[k] - self._starts[k]


@dataclass
class SampleTiming:
    """Working-time state for one attempt of a sample.

    Keeps the merged closed known-work intervals, the closed waits not covered
    by them, and their union, for the whole attempt. While any wait is open,
    the live wait runs from the start of the oldest open wait to now. Work
    still in progress (open spans, and model attempts not yet classified) is
    kept on its spans and read live.
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

    # closed known work
    _work: _IntervalSet = field(default_factory=_IntervalSet)
    # closed waits minus closed known work
    _waits: _IntervalSet = field(default_factory=_IntervalSet)
    # closed waits and closed known work
    _covered: _IntervalSet = field(default_factory=_IntervalSet)
    # spans whose work is not yet closed (open, or pending classification)
    _spans: dict["_WorkSpan", None] = field(default_factory=dict)

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
        """Merge the closed wait `[start, end]`, clipped to this attempt."""
        start, end = self._clip(start, end)
        if end <= start:
            return
        self._covered.add(start, end)
        self._waits.add_all(self._work.gaps(start, end))

    def add_work(self, start: float, end: float) -> None:
        """Merge the closed known work `[start, end]`, clipped to this attempt."""
        start, end = self._clip(start, end)
        if end <= start:
            return
        self._work.add(start, end)
        self._covered.add(start, end)
        self._waits.remove(start, end)

    def waiting(self, a: float, b: float) -> float:
        """Length of `[a, b]` covered by a known wait and by no known work."""
        b = min(b, self.now())
        if b <= a:
            return 0.0
        waiting = self._uncovered_waiting(a, b)
        for start, end in self._live_work(a, b):
            waiting -= self._uncovered_waiting(start, end)
        # bound float rounding in the prefix sums
        return min(max(waiting, 0.0), b - a)

    def elapsed(self) -> float:
        """Wall-clock time of this attempt so far."""
        return self.now() - self.start_time

    def working(self) -> float:
        """Working time of this attempt so far."""
        now = self.now()
        return (now - self.start_time) - self.waiting(self.start_time, now)

    def _clip(self, start: float, end: float) -> tuple[float, float]:
        return max(start, self.start_time), min(end, self.now())

    def _uncovered_waiting(self, a: float, b: float) -> float:
        """Waiting within `[a, b]`, not counting work still in progress."""
        waiting = self._waits.measure(a, b)
        if self.open_start is not None:
            lo = max(a, self.open_start)
            if b > lo:
                # the live wait, outside the closed waits and closed work
                waiting += (b - lo) - self._covered.measure(lo, b)
        return waiting

    def _live_work(self, a: float, b: float) -> list[tuple[float, float]]:
        """Work not yet closed, clipped to `[a, b]`, as disjoint intervals."""
        intervals: list[tuple[float, float]] = []
        for span in self._spans:
            intervals.extend(span.intervals(b))
        merged: list[tuple[float, float]] = []
        for s, e in sorted(intervals):
            s, e = max(s, a), min(e, b)
            if e <= s:
                continue
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        return merged


class _WorkSpan:
    """Known work in one task context, active while nothing in it is waiting.

    A wait or a nested span opened in the span's own context (including tasks
    it starts) holds it, so its time counts once, as the inner wait or work.
    A deferred span keeps its intervals until `commit()` or `discard()`, so a
    model attempt can be reclassified once its outcome is known.
    """

    def __init__(
        self, timing: SampleTiming, parent: "_WorkSpan | None", deferred: bool
    ) -> None:
        self._timing = timing
        self._parent = parent
        self._deferred = deferred
        self._holds = 0
        self._closed = False
        self._active_start: float | None = timing.now()
        self._pending: list[tuple[float, float]] = []
        timing._spans[self] = None
        if parent is not None:
            parent.hold()

    def hold(self) -> None:
        if self._holds == 0:
            self._end_active()
        self._holds += 1

    def release(self) -> None:
        self._holds -= 1
        if self._holds == 0 and not self._closed:
            self._active_start = self._timing.now()

    def close(self) -> None:
        if self._closed:
            return
        self._end_active()
        self._closed = True
        if not self._deferred:
            self._timing._spans.pop(self, None)
        if self._parent is not None:
            self._parent.release()

    def commit(self, work_from: float | None = None) -> None:
        """Record the pending intervals (from `work_from` on) as known work."""
        for start, end in self._pending:
            if work_from is not None:
                start = max(start, work_from)
            self._timing.add_work(start, end)
        self.discard()

    def discard(self) -> None:
        """Drop the pending intervals."""
        self._pending = []
        self._timing._spans.pop(self, None)

    def intervals(self, now: float) -> list[tuple[float, float]]:
        """Pending intervals, plus the active one up to `now`."""
        if self._active_start is None:
            return self._pending
        return self._pending + [(self._active_start, now)]

    def _end_active(self) -> None:
        start, self._active_start = self._active_start, None
        if start is None:
            return
        end = self._timing.now()
        if self._deferred:
            if end > start:
                self._pending.append((start, end))
        else:
            self._timing.add_work(start, end)


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


def sample_working_time_since(start: float) -> float:
    """Working time from `start` (sample clock) to now, within this attempt.

    Elapsed and waiting time are read over the same window, so the result
    lies in `[0, now - start]`.
    """
    timing = _sample_timing.get()
    if timing is None:
        return time.monotonic() - start
    now = timing.now()
    return (now - start) - timing.waiting(start, now)


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
    It holds the known work of the context that opened it.
    """

    def __init__(self) -> None:
        self._timing = _sample_timing.get()
        self._work = _current_work.get() if not _suspended.get() else None
        if self._timing is not None:
            self._timing.open_wait()
            if self._work is not None:
                self._work.hold()

    def close(self) -> None:
        if self._timing is not None:
            timing, self._timing = self._timing, None
            timing.close_wait()
            if self._work is not None:
                self._work.release()


@contextlib.contextmanager
def sample_wait() -> Iterator[None]:
    """Mark the sample as waiting while the block runs (no-op outside a sample).

    Work done inside the block is not known work, so it does not count as
    working time.
    """
    wait = SampleWait()
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)
        wait.close()


def _open_work(deferred: bool) -> _WorkSpan | None:
    timing = _sample_timing.get()
    if timing is None or _suspended.get():
        return None
    return _WorkSpan(timing, _current_work.get(), deferred)


@contextlib.contextmanager
def known_work() -> Iterator[None]:
    """Count the block as known work (no-op outside a sample or inside a wait)."""
    span = _open_work(deferred=False)
    if span is None:
        yield
        return
    token = _current_work.set(span)
    try:
        yield
    finally:
        _current_work.reset(token)
        span.close()


class ModelAttempts:
    """Known work of the attempts of one model call's retry loop.

    An attempt in flight is known work. Its intervals stay pending until the
    retry policy classifies it: `retried()` drops them (the retry loop records
    the attempt as a wait), and `commit()` records them as work.
    """

    def __init__(self) -> None:
        self._pending: list[_WorkSpan] = []

    @contextlib.contextmanager
    def attempt(self) -> Iterator[None]:
        """Count the block as an attempt in flight."""
        span = _open_work(deferred=True)
        if span is None:
            yield
            return
        self._pending.append(span)
        token = _current_work.set(span)
        try:
            yield
        finally:
            _current_work.reset(token)
            span.close()

    def commit(self, work_from: float | None = None) -> None:
        """Record the pending attempts as known work.

        Args:
           work_from: Start of the known work on the sample clock (the time
              before it went to the provider SDK's own retries).
        """
        for span in self._pending:
            span.commit(work_from)
        self._pending = []

    def retried(self) -> None:
        """Drop the pending attempts, which the retry loop records as waits."""
        for span in self._pending:
            span.discard()
        self._pending = []


_sample_timing: ContextVar[SampleTiming | None] = ContextVar(
    "sample_timing", default=None
)

# the innermost known work of this context
_current_work: ContextVar[_WorkSpan | None] = ContextVar(
    "sample_current_work", default=None
)

# inside a known wait that covers its own work (`sample_wait()`)
_suspended: ContextVar[bool] = ContextVar("sample_work_suspended", default=False)


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
