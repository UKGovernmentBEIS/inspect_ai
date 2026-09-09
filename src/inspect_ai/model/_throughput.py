"""Process-global per-model throughput registry.

Answers the operator question "what effective throughput am I getting from
each model right now, and is it worth waiting?" during sustained HTTP
retries (see ``design/model-throughput.md``). Fed from the existing
accounting funnels — ``record_and_check_model_usage()`` for tokens,
``report_http_retry()`` for retry counts, and the model retry loop's
before-sleep callback for scheduled backoff — and read by the
``GET /models/throughput`` control endpoint, the trace surface, and the
live display footer.

Keys are the full qualified ``provider/model`` name (the same key
``model_usage`` uses); see the "Key discipline" section of the design doc
for how each feed obtains it. Records with no qualified name in hand are
simply not attributed here (they still count toward the legacy global
retry scalar).

No lock: writes and reads happen on the eval's single event loop thread
(control-server handlers included), per the repo's no-speculative-locks
rule; individual updates don't span awaits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import getLogger
from typing import Any, Literal, NamedTuple

from inspect_ai._util.constants import HTTP

from ._model_output import ModelUsage

logger = getLogger(__name__)

RetryKind = Literal["rate_limit", "transient"]

BUCKET_SECONDS = 10
"""Width of one ring bucket."""

BUCKET_COUNT = 60
"""Number of ring buckets."""

HORIZON_SECONDS = BUCKET_SECONDS * BUCKET_COUNT
"""Maximum lookback window (10 minutes)."""

DEFAULT_WINDOW_SECONDS = 60
"""Default rate window for snapshots."""

_BACKOFF_PRUNE_MIN = 64
"""Floor for the backoff-interval prune threshold."""


class _WindowSums(NamedTuple):
    output_tokens: int
    total_tokens: int
    requests: int
    retries: int


@dataclass
class _Bucket:
    # absolute bucket epoch (monotonic seconds // BUCKET_SECONDS); a slot is
    # reused for many epochs over time, so reads must check it — a stale
    # epoch means the slot's counts belong to a lap the window excludes
    epoch: int = -1
    output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    retries: int = 0


class TokenBuckets:
    """Fixed-length ring of time buckets on the monotonic clock.

    Bounds memory to a constant per model regardless of request rate (a
    per-request deque would grow with throughput — exactly the case this
    registry exists for). Writes are O(1); reads sum at most
    ``BUCKET_COUNT`` buckets. Slots are epoch-tagged rather than zeroed on
    advance: a write resets a slot whose stored epoch differs from the
    current one, and reads include only slots whose epoch falls inside the
    requested window, so gaps in traffic can't leak a previous lap's counts
    into a window sum. Window boundaries have bucket granularity — the sum
    covers whole buckets overlapping ``[now - window, now]``.
    """

    def __init__(self) -> None:
        self._buckets = [_Bucket() for _ in range(BUCKET_COUNT)]

    def add(
        self,
        now: float,
        *,
        output_tokens: int = 0,
        total_tokens: int = 0,
        requests: int = 0,
        retries: int = 0,
    ) -> None:
        epoch = int(now // BUCKET_SECONDS)
        bucket = self._buckets[epoch % BUCKET_COUNT]
        if bucket.epoch != epoch:
            bucket.epoch = epoch
            bucket.output_tokens = 0
            bucket.total_tokens = 0
            bucket.requests = 0
            bucket.retries = 0
        bucket.output_tokens += output_tokens
        bucket.total_tokens += total_tokens
        bucket.requests += requests
        bucket.retries += retries

    def window_sums(self, now: float, window: float) -> _WindowSums:
        window = min(window, HORIZON_SECONDS)
        lo_epoch = int((now - window) // BUCKET_SECONDS)
        hi_epoch = int(now // BUCKET_SECONDS)
        output_tokens = total_tokens = requests = retries = 0
        for bucket in self._buckets:
            if lo_epoch <= bucket.epoch <= hi_epoch:
                output_tokens += bucket.output_tokens
                total_tokens += bucket.total_tokens
                requests += bucket.requests
                retries += bucket.retries
        return _WindowSums(output_tokens, total_tokens, requests, retries)


class BackoffInterval(NamedTuple):
    """A scheduled retry backoff on the monotonic clock.

    Kept out of the bucket ring: sleeps reach 30 minutes, so attributing one
    to its schedule-time bucket would swamp any window containing its start,
    while pre-writing future buckets fights the ring's slot reuse. Reads
    compute a window's backoff-seconds as each interval's overlap with the
    window instead. Pruning (see ``record_retry_wait``) keeps the list
    within 2× the live intervals — those still in backoff or ended inside
    the horizon — so it stays concurrency-bound, not request-rate-bound.
    """

    start: float
    end: float


@dataclass
class ModelThroughput:
    """Accumulated throughput state for one model (registry value)."""

    # cumulative since run start
    requests: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    retries_rate_limit: int = 0
    retries_transient: int = 0
    retry_wait_seconds: float = 0.0
    first_activity: datetime | None = None
    last_activity: datetime | None = None
    # monotonic first-activity for clamping fresh-run windows
    first_activity_monotonic: float | None = None
    # rolling window
    buckets: TokenBuckets = field(default_factory=TokenBuckets)
    backoff_intervals: list[BackoffInterval] = field(default_factory=list)
    # list size that triggers the next backoff-interval prune
    backoff_prune_at: int = _BACKOFF_PRUNE_MIN


@dataclass(frozen=True)
class ModelThroughputView:
    """Read-side snapshot for one model, with derived rates."""

    model: str
    window_seconds: float
    output_tokens_per_second: float
    requests_per_minute: float
    retries_per_minute: float
    backoff_ratio: float
    retry_waits_active: int
    # cumulative since run start
    requests: int
    output_tokens: int
    total_tokens: int
    retries_rate_limit: int
    retries_transient: int
    retry_wait_seconds: float
    first_activity: datetime | None
    last_activity: datetime | None


_registry: dict[str, ModelThroughput] = {}

_RETRY_WAITS_MEMO_SECONDS = 1.0
"""TTL of the ``_retry_waits_active()`` memo."""


class _RetryWaitsMemo(NamedTuple):
    """Result of the last active-waits scan, for reuse within the TTL."""

    scanned_at: float
    """Monotonic timestamp of the scan."""

    counts: dict[str, int]
    """Samples in an active retry wait, per qualified model."""


_retry_waits_memo: _RetryWaitsMemo | None = None


def init_model_throughput() -> None:
    """Clear the registry (wired into ``reset_run_registries()``).

    Deliberately unlike the never-reset ``_http_retries_count`` scalar: a
    keep-alive process's second run (and each test) starts clean.
    """
    global _retry_waits_memo
    _registry.clear()
    _retry_waits_memo = None


def _record(model: str, now: float | None) -> tuple[ModelThroughput, float]:
    now = time.monotonic() if now is None else now
    record = _registry.get(model)
    if record is None:
        record = ModelThroughput()
        _registry[model] = record
    wall = datetime.now(timezone.utc)
    if record.first_activity is None:
        record.first_activity = wall
        record.first_activity_monotonic = now
    record.last_activity = wall
    return record, now


def record_generate(model: str, usage: ModelUsage, now: float | None = None) -> None:
    """Record a completed generate's usage for ``model`` (qualified name).

    Called from ``record_and_check_model_usage()`` — which cache hits bypass
    via their early return, so cached reads (which consume no provider
    capacity) never inflate the reported rate.
    """
    record, now = _record(model, now)
    record.requests += 1
    record.output_tokens += usage.output_tokens
    record.total_tokens += usage.total_tokens
    record.buckets.add(
        now,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        requests=1,
    )


def record_retry(model: str, kind: RetryKind, now: float | None = None) -> None:
    """Record an HTTP retry for ``model`` (qualified name)."""
    record, now = _record(model, now)
    if kind == "rate_limit":
        record.retries_rate_limit += 1
    else:
        record.retries_transient += 1
    record.buckets.add(now, retries=1)


def record_retry_wait(
    model: str, wait_seconds: float, now: float | None = None
) -> None:
    """Record a scheduled retry backoff of ``wait_seconds`` for ``model``.

    Prunes intervals that ended more than a horizon ago (no window reaches
    them). The head check catches the common case cheaply, but the head can
    be the longest-lived entry — a 30-minute sleep keeps its end past the
    cutoff for up to ~40 minutes while short waits pile up behind it — so a
    size threshold (doubled after each rebuild, keeping pruning amortized
    O(1)) bounds growth in that case too.
    """
    record, now = _record(model, now)
    record.retry_wait_seconds += wait_seconds
    intervals = record.backoff_intervals
    intervals.append(BackoffInterval(now, now + wait_seconds))
    cutoff = now - HORIZON_SECONDS
    if intervals[0].end < cutoff or len(intervals) >= record.backoff_prune_at:
        record.backoff_intervals = [
            interval for interval in intervals if interval.end >= cutoff
        ]
        record.backoff_prune_at = max(
            2 * len(record.backoff_intervals), _BACKOFF_PRUNE_MIN
        )


def _window_backoff_seconds(
    intervals: list[BackoffInterval], now: float, window: float
) -> float:
    """Sum of each interval's overlap with ``[now - window, now]``.

    Only elapsed backoff counts (an interval's future portion is excluded),
    so ``backoff_ratio`` reads as backoff-seconds accumulated per wall-clock
    second — summed across concurrent generates, hence able to exceed 1.0.
    """
    lo = now - window
    return sum(
        max(0.0, min(interval.end, now) - max(interval.start, lo))
        for interval in intervals
    )


def _retry_waits_active() -> dict[str, int]:
    """Count active samples currently sleeping in a retry wait, per qualified model.

    Bounded by active sample count. ``ActiveSample.retry_wait`` is a single
    shared slot per sample, so parallel generates within one sample count
    as one. The record is cleared only when the whole retried call resolves
    (not when its sleep elapses), so filter on the deadline — a stale record
    means the next attempt is actively generating, not backing off.

    Memoized for ~1s: the hottest caller is the per-retry trace line
    (unthrottled, and retry storms peak exactly when active samples do), so
    without the memo each retry would pay an O(active samples) scan. A
    second of staleness is noise against the 3s-to-30min sleeps the counts
    describe. The memo resets with the registry in
    ``init_model_throughput()``.
    """
    global _retry_waits_memo
    from inspect_ai.log._samples import active_samples

    now_monotonic = time.monotonic()
    if (
        _retry_waits_memo is not None
        and now_monotonic - _retry_waits_memo.scanned_at < _RETRY_WAITS_MEMO_SECONDS
    ):
        return _retry_waits_memo.counts

    now = datetime.now(timezone.utc).timestamp()
    counts: dict[str, int] = {}
    for sample in active_samples():
        retry_wait = sample.retry_wait
        if (
            retry_wait is not None
            and retry_wait.qualified_model
            and retry_wait.deadline > now
        ):
            counts[retry_wait.qualified_model] = (
                counts.get(retry_wait.qualified_model, 0) + 1
            )
    _retry_waits_memo = _RetryWaitsMemo(scanned_at=now_monotonic, counts=counts)
    return counts


def _model_view(
    model: str,
    record: ModelThroughput,
    retry_waits_active: int,
    now: float,
    window: int,
) -> ModelThroughputView:
    """One model's view over the trailing ``window`` seconds.

    ``window`` is additionally clamped to time-since-first-activity so a
    fresh run doesn't report an artificially diluted rate.
    """
    effective = float(window)
    if record.first_activity_monotonic is not None:
        effective = min(effective, now - record.first_activity_monotonic)
    effective = max(effective, 1.0)
    sums = record.buckets.window_sums(now, effective)
    backoff = _window_backoff_seconds(record.backoff_intervals, now, effective)
    return ModelThroughputView(
        model=model,
        window_seconds=effective,
        output_tokens_per_second=sums.output_tokens / effective,
        requests_per_minute=sums.requests * 60.0 / effective,
        retries_per_minute=sums.retries * 60.0 / effective,
        backoff_ratio=backoff / effective,
        retry_waits_active=retry_waits_active,
        requests=record.requests,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        retries_rate_limit=record.retries_rate_limit,
        retries_transient=record.retries_transient,
        retry_wait_seconds=record.retry_wait_seconds,
        first_activity=record.first_activity,
        last_activity=record.last_activity,
    )


def throughput_snapshot(
    window: int = DEFAULT_WINDOW_SECONDS, now: float | None = None
) -> dict[str, ModelThroughputView]:
    """Per-model throughput views over the trailing ``window`` seconds.

    ``window`` is clamped to the bucket horizon (per-model clamping in
    ``_model_view``).
    """
    now = time.monotonic() if now is None else now
    window = max(1, min(window, HORIZON_SECONDS))
    waits_active = _retry_waits_active()
    return {
        model: _model_view(model, record, waits_active.get(model, 0), now, window)
        for model, record in _registry.items()
    }


def throughput_view(
    model: str, window: int = DEFAULT_WINDOW_SECONDS
) -> ModelThroughputView | None:
    """Snapshot for one model, or None if it has no recorded activity.

    Computes only the requested model's view (this runs on every retry
    trace line, so it must stay independent of registry size; the active
    sample scan is memoized in ``_retry_waits_active``).
    """
    record = _registry.get(model)
    if record is None:
        return None
    return _model_view(
        model,
        record,
        _retry_waits_active().get(model, 0),
        time.monotonic(),
        max(1, min(window, HORIZON_SECONDS)),
    )


def throughput_report(window: int = DEFAULT_WINDOW_SECONDS) -> dict[str, Any]:
    """The ``GET /models/throughput`` response envelope.

    The envelope ``window_seconds`` is the requested (clamped) window; each
    model row carries its *effective* ``window_seconds`` (further clamped to
    time-since-first-activity), so a consumer recovering counts from rates
    (rate × window) isn't misled for a model younger than the window.

    Cheap-shoveling compliant: everything was materialized at write time —
    the read is a bounded sum over the ring buckets and backoff intervals of
    each model, plus one bounded pass over active samples.
    """

    def iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt is not None else None

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "window_seconds": max(1, min(window, HORIZON_SECONDS)),
        "models": [
            {
                "model": view.model,
                "window_seconds": round(view.window_seconds, 1),
                "output_tokens_per_second": round(view.output_tokens_per_second, 1),
                "requests_per_minute": round(view.requests_per_minute, 1),
                "retries_per_minute": round(view.retries_per_minute, 1),
                "backoff_ratio": round(view.backoff_ratio, 2),
                "retry_waits_active": view.retry_waits_active,
                "cumulative": {
                    "requests": view.requests,
                    "output_tokens": view.output_tokens,
                    "total_tokens": view.total_tokens,
                    "retries": {
                        "rate_limit": view.retries_rate_limit,
                        "transient": view.retries_transient,
                    },
                    "retry_wait_seconds": round(view.retry_wait_seconds, 1),
                    "first_activity_at": iso(view.first_activity),
                    "last_activity_at": iso(view.last_activity),
                },
            }
            for _, view in sorted(throughput_snapshot(window).items())
        ],
    }


def throughput_footer_rate(window: int = DEFAULT_WINDOW_SECONDS) -> float | None:
    """Aggregate output tok/s for the display footer, or None when quiet.

    None until any retry has been recorded this run — a healthy run's footer
    doesn't gain a noisy number. Gated on this registry (reset per run via
    ``reset_run_registries()``), not the never-reset global retry scalar, so
    a keep-alive process's second run starts quiet.
    """
    if not any(
        record.retries_rate_limit or record.retries_transient
        for record in _registry.values()
    ):
        return None
    return sum(
        view.output_tokens_per_second for view in throughput_snapshot(window).values()
    )


async def report_throughput_periodically(interval: float = 60.0) -> None:
    """Emit a per-model ``[Throughput]`` trace line each interval.

    Run-scoped (started on the eval run's task group, cancelled with the
    run). Logs at the ``HTTP`` level directly — not ``trace_message()``,
    which logs at ``TRACE`` and would not appear under ``inspect trace
    http`` — and only for models that retried during the interval, so quiet
    runs add zero trace noise.
    """
    import anyio

    last_retries: dict[str, int] = {}
    while True:
        await anyio.sleep(interval)
        for model, view in sorted(throughput_snapshot(window=int(interval)).items()):
            retries = view.retries_rate_limit + view.retries_transient
            if retries > last_retries.get(model, 0):
                logger.log(
                    HTTP,
                    f"[Throughput] {model}: "
                    f"{view.output_tokens_per_second:,.1f} out-tok/s, "
                    f"{view.requests_per_minute:,.1f} req/min, "
                    f"{view.retries_per_minute:,.1f} retries/min, "
                    f"{view.retry_waits_active} in backoff "
                    f"(window {int(view.window_seconds)}s)",
                )
            last_retries[model] = retries
