"""Sample working time: wall-clock time minus known waits not covered by known work.

Each instant of a sample is working if any known work is in progress (a model
attempt, a sandbox exec or a tool call that is not itself waiting), otherwise
waiting if any known wait is open anywhere in the sample, and otherwise
working. Waits and work are each merged, never added, so working time always
lies between zero and the elapsed time. See design/working-time-concurrency.md.
"""

import contextlib
import math
import time
from bisect import bisect_left, bisect_right
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Iterator


class _Timeline:
    """Closed waits and closed known work, as sorted, disjoint segments.

    Each segment records whether a closed wait covers it and how many spans'
    closed work covers it; time in no segment has neither. Adjacent segments
    with the same state are merged. Prefix sums give the length of the
    waiting segments (a wait and no work) and of all segments (a wait or
    work) before each segment.
    """

    def __init__(self) -> None:
        self._starts: list[float] = []
        self._ends: list[float] = []
        self._waited: list[bool] = []
        self._counts: list[int] = []
        # `_waiting[i]` and `_covered[i]` are the totals of segments `0..i-1`
        self._waiting: list[float] = []
        self._covered: list[float] = []

    def change(
        self, start: float, end: float, wait: bool = False, work: int = 0
    ) -> None:
        """Mark `[start, end]` as waited if `wait`, and add `work` to its work count.

        A negative `work` withdraws work added before; the count stops at zero.
        """
        if end <= start:
            return
        # segments that overlap or touch `[start, end]`, so equal neighbours merge
        i = bisect_left(self._ends, start)
        j = bisect_right(self._starts, end)
        pieces: list[tuple[float, float, bool, int]] = []

        def put(s: float, e: float, waited: bool, count: int) -> None:
            if e <= s or not (waited or count):
                return
            if pieces and pieces[-1][1] == s and pieces[-1][2:] == (waited, count):
                pieces[-1] = (pieces[-1][0], e, waited, count)
            else:
                pieces.append((s, e, waited, count))

        cursor = start
        for k in range(i, j):
            s, e = self._starts[k], self._ends[k]
            waited, count = self._waited[k], self._counts[k]
            put(s, min(e, start), waited, count)
            put(cursor, s, wait, max(work, 0))
            put(max(s, start), min(e, end), waited or wait, max(count + work, 0))
            put(max(s, end), e, waited, count)
            cursor = max(cursor, min(e, end))
        put(cursor, end, wait, max(work, 0))
        self._splice(i, j, pieces)

    def waiting(self, a: float, b: float) -> float:
        """Length of `[a, b]` covered by a closed wait and no closed work."""
        return self._waiting_before(b) - self._waiting_before(a) if b > a else 0.0

    def covered(self, a: float, b: float) -> float:
        """Length of `[a, b]` covered by a closed wait or closed work."""
        return self._covered_before(b) - self._covered_before(a) if b > a else 0.0

    def _segment(self, x: float) -> tuple[int, float]:
        """The last segment starting at or before `x`, and its length before `x`."""
        k = bisect_right(self._starts, x) - 1
        return k, (min(x, self._ends[k]) - self._starts[k] if k >= 0 else 0.0)

    def _waiting_before(self, x: float) -> float:
        k, part = self._segment(x)
        if k < 0:
            return 0.0
        return self._waiting[k] + (part if self._is_waiting(k) else 0.0)

    def _covered_before(self, x: float) -> float:
        k, part = self._segment(x)
        return self._covered[k] + part if k >= 0 else 0.0

    def _is_waiting(self, k: int) -> bool:
        return self._waited[k] and not self._counts[k]

    def _splice(
        self, i: int, j: int, pieces: list[tuple[float, float, bool, int]]
    ) -> None:
        self._starts[i:j] = [s for s, _, _, _ in pieces]
        self._ends[i:j] = [e for _, e, _, _ in pieces]
        self._waited[i:j] = [w for _, _, w, _ in pieces]
        self._counts[i:j] = [c for _, _, _, c in pieces]
        self._waiting[i:j] = [0.0] * len(pieces)
        self._covered[i:j] = [0.0] * len(pieces)
        waiting, covered = 0.0, 0.0
        if i:
            length = self._ends[i - 1] - self._starts[i - 1]
            waiting = self._waiting[i - 1] + (
                length if self._is_waiting(i - 1) else 0.0
            )
            covered = self._covered[i - 1] + length
        for k in range(i, len(self._starts)):
            self._waiting[k], self._covered[k] = waiting, covered
            length = self._ends[k] - self._starts[k]
            covered += length
            if self._is_waiting(k):
                waiting += length


@dataclass
class SampleTiming:
    """Working-time state for one attempt of a sample.

    Keeps, for the whole attempt, one timeline of the closed waits and the
    closed known work (counted per span, so one span's work can be
    withdrawn). While any wait is open, the live wait runs from the start of
    the oldest open wait to now. Work still in progress (open spans, and model
    attempts not yet classified) is kept on its spans and read live.
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

    # closed waits and closed known work
    _timeline: _Timeline = field(default_factory=_Timeline)
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

    def add_wait(
        self,
        start: float,
        end: float,
        owner: "_WorkSpan | None" = None,
        completed: bool = True,
    ) -> None:
        """Merge the closed wait `[start, end]`, clipped to this attempt.

        Args:
           start: Start of the wait on the sample clock.
           end: End of the wait on the sample clock.
           owner: The known work of the context the wait was in. A wait
              reported after the fact is withdrawn from that work and its
              enclosing work, as if it had held them.
           completed: Also withdraw the work of other spans that finished
              under `owner` and its enclosing work (handed to them when it
              was final). Otherwise only the work those spans counted
              themselves is withdrawn.
        """
        start, end = self._clip(start, end)
        if end <= start:
            return
        self._timeline.change(start, end, wait=True)
        chain: list[_WorkSpan] = []
        while owner is not None:
            chain.append(owner)
            owner = owner._parent
        origins = None if completed else set(chain)
        for span in chain:
            span.withdraw(start, end, origins)

    def add_work(self, start: float, end: float) -> tuple[float, float] | None:
        """Count the closed known work `[start, end]`, clipped to this attempt.

        Returns the interval counted, if any, for `remove_work()`.
        """
        start, end = self._clip(start, end)
        if end <= start:
            return None
        self._timeline.change(start, end, work=1)
        return start, end

    def remove_work(self, start: float, end: float) -> None:
        """Withdraw known work counted by `add_work()`."""
        self._timeline.change(start, end, work=-1)

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
        waiting = self._timeline.waiting(a, b)
        if self.open_start is not None:
            lo = max(a, self.open_start)
            if b > lo:
                # the live wait, outside the closed waits and closed work
                waiting += (b - lo) - self._timeline.covered(lo, b)
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
    A span holds its parent while it is open, and after it closes for as long
    as something still holds it, so a task that outlives the span still holds
    the open work above it. A deferred span keeps its intervals until
    `commit()` or `discard()`, so a model attempt can be reclassified once its
    outcome is known.

    Once its work is final (at `close()`, or at `commit()` or `discard()` for a
    deferred span), a span hands the intervals it counted, and those handed to
    it, to its parent, so a wait reported later from the parent's context can
    withdraw them. Each interval keeps the span that counted it. A span with
    no parent drops them.
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
        # intervals not yet counted (deferred spans only)
        self._pending: list[tuple[float, float]] = []
        # intervals counted as known work, by this span or by spans that have
        # handed their work to it, with the span that counted each
        self._counted: list[tuple[_WorkSpan, float, float]] = []
        self._handed_off = False
        timing._spans[self] = None
        if parent is not None:
            parent.hold()

    def hold(self) -> None:
        if self._holds == 0:
            if self._closed:
                if self._parent is not None:
                    self._parent.hold()
            else:
                self._end_active()
        self._holds += 1

    def release(self) -> None:
        self._holds -= 1
        if self._holds == 0:
            if self._closed:
                if self._parent is not None:
                    self._parent.release()
            else:
                self._active_start = self._timing.now()

    def close(self) -> None:
        if self._closed:
            return
        self._end_active()
        self._closed = True
        if not self._deferred:
            self._timing._spans.pop(self, None)
        if self._holds == 0 and self._parent is not None:
            self._parent.release()
        if not self._deferred:
            self._hand_off()

    def commit(self) -> None:
        """Count the pending intervals as known work."""
        for start, end in self._pending:
            self._count(start, end)
        self.discard()

    def discard(self) -> None:
        """Drop the pending intervals."""
        self._pending = []
        self._timing._spans.pop(self, None)
        self._hand_off()

    def withdraw(
        self, start: float, end: float, origins: "set[_WorkSpan] | None"
    ) -> None:
        """Stop counting `[start, end]` as work of this span or handed to it.

        Args:
           start: Start of the interval.
           end: End of the interval.
           origins: Withdraw only the intervals these spans counted (all of
              them, if `None`).
        """
        active = self._active_start is not None
        self._end_active()
        self._pending = _subtract(self._pending, start, end)
        kept: list[tuple[_WorkSpan, float, float]] = []
        for origin, s, e in self._counted:
            if s < end and e > start and (origins is None or origin in origins):
                self._timing.remove_work(s, e)
                for piece in _subtract([(s, e)], start, end):
                    recounted = self._timing.add_work(*piece)
                    if recounted is not None:
                        kept.append((origin, *recounted))
            else:
                kept.append((origin, s, e))
        self._counted = kept
        if active:
            self._active_start = self._timing.now()

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
            self._count(start, end)

    def _count(self, start: float, end: float) -> None:
        counted = self._timing.add_work(start, end)
        if counted is not None:
            self._counted.append((self, *counted))

    def _hand_off(self) -> None:
        """Pass the counted intervals to the parent; the span's work is final."""
        counted, self._counted = self._counted, []
        self._handed_off = True
        self._receive(counted)

    def _receive(self, counted: list[tuple["_WorkSpan", float, float]]) -> None:
        if not self._handed_off:
            self._counted.extend(counted)
        elif self._parent is not None:
            self._parent._receive(counted)


def _subtract(
    intervals: list[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    """`intervals` without `[start, end]`."""
    result: list[tuple[float, float]] = []
    for s, e in intervals:
        if e <= start or s >= end:
            result.append((s, e))
            continue
        if s < start:
            result.append((s, start))
        if e > end:
            result.append((end, e))
    return result


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
    merged with the waits already known. See `add_sample_wait()` for the
    known work that is not counted over the interval.
    """
    timing = _sample_timing.get()
    if timing is not None:
        now = timing.now()
        timing.add_wait(now - waiting_time, now, _current_work.get())


def add_sample_wait(start: float, end: float, completed: bool = True) -> None:
    """Record the closed interval `[start, end]` (sample clock) as a known wait.

    The known work of the calling context (and the work enclosing it) is not
    counted over the interval, as if the wait had held it while open. This
    includes work that has already finished inside it, such as a model call
    or sandbox command that returned before the report, and holds inside a
    wait such as `suspend_working_limit()` too: the wait stops new work there,
    not the history of the work around it.

    Finished work includes that of tasks started inside the enclosing work
    (subtasks a tool started, say), although a wait opened at the time would
    not have stopped them. Outside any known work, at the sample's top level,
    there is none to withdraw, so a call made there leaves finished work
    charged: wrap the operation in `sample_wait()` instead. The same holds for
    a top-level tool call's work once it has returned.

    Args:
       start: Start of the wait on the sample clock.
       end: End of the wait on the sample clock.
       completed: Withdraw other finished work too. A model call passes
          `False` for its own retries (retried attempts, SDK-internal
          retries): the attempt's work is dropped or trimmed on the attempt
          itself, and other work that finished beside it stays charged,
          while the calling context's own work (and that of the work
          enclosing it) is still withdrawn.
    """
    timing = _sample_timing.get()
    if timing is not None:
        timing.add_wait(start, end, _current_work.get(), completed)


class SampleWait:
    """A known wait that stays open until `close()` (idempotent).

    Bound to the sample whose context opened it, so another task may close it.
    It holds the known work of the context that opened it.
    """

    def __init__(self) -> None:
        self._timing = _sample_timing.get()
        # held even when opened inside a suspension, which the wait may outlive
        self._work = _current_work.get()
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
    if _sample_timing.get() is None:
        yield
        return
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
def untracked_sandbox_execs() -> Iterator[None]:
    """Sandbox execs this task runs inside the block are not known work.

    For Inspect's own plumbing (sandbox service queues, `exec_remote` polls,
    tool injection), and for execs whose work Inspect cannot see, such as a
    bridged agent's launcher or the human agent's service. Such an exec does
    not override a known wait; with no wait open, its time is working.
    """
    token = _untracked_sandbox_execs.set(True)
    try:
        yield
    finally:
        _untracked_sandbox_execs.reset(token)


def sandbox_exec_work() -> contextlib.AbstractContextManager[None]:
    """Known work for a sandbox exec, unless inside `untracked_sandbox_execs()`."""
    if _untracked_sandbox_execs.get():
        return contextlib.nullcontext()
    return known_work()


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
    retry loop is done with it: `retried()` drops them (the retry loop records
    the attempt as a wait), and `commit()`, once the loop has returned or
    raised, records them as work.
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

    def exclude_before(self, start: float) -> None:
        """Stop counting the pending attempts' time before `start` as work.

        Used for the time a successful attempt spent in the provider SDK's own
        retries. The attempts stay pending, so a later retry still drops them.
        """
        for span in self._pending:
            span.withdraw(-math.inf, start, origins={span})

    def commit(self) -> None:
        """Record the pending attempts as known work."""
        for span in self._pending:
            span.commit()
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

# inside `untracked_sandbox_execs()`
_untracked_sandbox_execs: ContextVar[bool] = ContextVar(
    "sample_untracked_sandbox_execs", default=False
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
