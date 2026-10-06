"""Tests for the per-model throughput registry (design/model-throughput.md).

Covers the ring-bucket/backoff-interval mechanics with an injected clock,
the instrumentation feeds (generate usage, retry counts, retry waits), the
cache-hit exclusion regression, per-run reset, and the footer gate.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from tenacity import RetryCallState

from inspect_ai._util.retry import report_http_retry
from inspect_ai.model import get_model
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.model._retry import model_retry_config
from inspect_ai.model._throughput import (
    BUCKET_SECONDS,
    HORIZON_SECONDS,
    BackoffInterval,
    TokenBuckets,
    _window_backoff_seconds,
    init_model_throughput,
    record_generate,
    record_retry,
    record_retry_wait,
    throughput_footer_rate,
    throughput_report,
    throughput_snapshot,
    throughput_view,
)


@pytest.fixture(autouse=True)
def clean_registry():
    init_model_throughput()
    yield
    init_model_throughput()


def _usage(output_tokens: int = 10, total_tokens: int = 30) -> ModelUsage:
    return ModelUsage(
        input_tokens=total_tokens - output_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


# ---------------------------------------------------------------------------
# TokenBuckets
# ---------------------------------------------------------------------------


def test_buckets_window_sums() -> None:
    buckets = TokenBuckets()
    buckets.add(1000.0, output_tokens=10, total_tokens=20, requests=1)
    buckets.add(1030.0, output_tokens=5, total_tokens=10, requests=1, retries=2)
    sums = buckets.window_sums(1040.0, window=60)
    assert sums.output_tokens == 15
    assert sums.total_tokens == 30
    assert sums.requests == 2
    assert sums.retries == 2
    # a narrow window excludes the older write
    sums = buckets.window_sums(1040.0, window=BUCKET_SECONDS)
    assert sums.output_tokens == 5
    assert sums.retries == 2


def test_buckets_gap_does_not_leak_previous_lap() -> None:
    # a slot reused after a full lap of the ring must not leak the old lap's
    # counts into a window sum (the ring is epoch-tagged, not zeroed on a
    # timer)
    buckets = TokenBuckets()
    buckets.add(0.0, output_tokens=100)
    # more than a full horizon later, the epoch-0 write maps to a slot the
    # ring is about to reuse — it must be invisible to any window
    later = float(HORIZON_SECONDS + BUCKET_SECONDS)
    sums = buckets.window_sums(later + 5, window=HORIZON_SECONDS)
    assert sums.output_tokens == 0
    buckets.add(later, output_tokens=7)
    sums = buckets.window_sums(later + 5, window=HORIZON_SECONDS)
    assert sums.output_tokens == 7


def test_buckets_window_clamped_to_horizon() -> None:
    buckets = TokenBuckets()
    buckets.add(0.0, output_tokens=100)
    buckets.add(float(HORIZON_SECONDS * 2), output_tokens=1)
    sums = buckets.window_sums(float(HORIZON_SECONDS * 2), window=10 * HORIZON_SECONDS)
    assert sums.output_tokens == 1


# ---------------------------------------------------------------------------
# Backoff intervals
# ---------------------------------------------------------------------------


def test_backoff_overlap_partial_and_future_excluded() -> None:
    # interval started 30s ago and extends 30s into the future: only the
    # elapsed portion inside the window counts
    intervals = [BackoffInterval(70.0, 130.0)]
    assert _window_backoff_seconds(intervals, now=100.0, window=60.0) == 30.0
    # fully inside the window
    intervals = [BackoffInterval(50.0, 60.0)]
    assert _window_backoff_seconds(intervals, now=100.0, window=60.0) == 10.0
    # ended before the window opened
    intervals = [BackoffInterval(0.0, 30.0)]
    assert _window_backoff_seconds(intervals, now=100.0, window=60.0) == 0.0
    # concurrent intervals sum (backoff_ratio may exceed 1.0)
    intervals = [BackoffInterval(40.0, 100.0), BackoffInterval(40.0, 100.0)]
    assert _window_backoff_seconds(intervals, now=100.0, window=60.0) == 120.0


def test_backoff_intervals_pruned_past_horizon() -> None:
    record_retry_wait("test/m", 10.0, now=0.0)
    record_retry_wait("test/m", 10.0, now=float(HORIZON_SECONDS * 2))
    from inspect_ai.model._throughput import _registry

    intervals = _registry["test/m"].backoff_intervals
    assert len(intervals) == 1
    assert intervals[0].start == float(HORIZON_SECONDS * 2)


def test_backoff_intervals_pruned_behind_long_head() -> None:
    # a 30-minute sleep at the head keeps its end past the cutoff for the
    # whole test, so head-expiry alone would never prune; the size-threshold
    # backstop must still bound growth from short waits piling up behind it
    from inspect_ai.model._throughput import _registry

    head_wait = 30.0 * 60.0
    record_retry_wait("test/m", head_wait, now=0.0)
    for i in range(1, 1001):
        record_retry_wait("test/m", 0.1, now=i * 2.0)

    intervals = _registry["test/m"].backoff_intervals
    # bounded well below the 1001 appends (≤ 2× the live intervals: the head
    # plus short waits still inside the horizon)
    assert len(intervals) < 700
    # the still-live head survived every prune
    assert intervals[0] == BackoffInterval(0.0, head_wait)


# ---------------------------------------------------------------------------
# Registry + snapshot
# ---------------------------------------------------------------------------


def test_snapshot_rates_and_cumulative() -> None:
    record_generate("test/m", _usage(output_tokens=120, total_tokens=300), now=1000.0)
    record_generate("test/m", _usage(output_tokens=120, total_tokens=300), now=1030.0)
    record_retry("test/m", "rate_limit", now=1030.0)
    record_retry("test/m", "transient", now=1030.0)
    record_retry_wait("test/m", 30.0, now=1030.0)

    view = throughput_snapshot(window=60, now=1060.0)["test/m"]
    # effective window clamped to time-since-first-activity (60s)
    assert view.window_seconds == 60.0
    assert view.output_tokens_per_second == pytest.approx(240 / 60)
    assert view.requests_per_minute == pytest.approx(2.0)
    assert view.retries_per_minute == pytest.approx(2.0)
    # 30s elapsed of the scheduled 30s backoff / 60s window
    assert view.backoff_ratio == pytest.approx(0.5)
    assert view.requests == 2
    assert view.output_tokens == 240
    assert view.total_tokens == 600
    assert view.retries_rate_limit == 1
    assert view.retries_transient == 1
    assert view.retry_wait_seconds == 30.0
    assert view.first_activity is not None and view.last_activity is not None


def test_snapshot_clamps_fresh_run_window() -> None:
    # 10 seconds after first activity, a 60s window must not dilute the rate
    record_generate("test/m", _usage(output_tokens=100), now=1000.0)
    view = throughput_snapshot(window=60, now=1010.0)["test/m"]
    assert view.window_seconds == pytest.approx(10.0)
    assert view.output_tokens_per_second == pytest.approx(10.0)


def test_report_http_retry_attributes_model() -> None:
    report_http_retry(kind="rate_limit", model="test/m")
    report_http_retry()  # no model context: global scalar only
    view = throughput_view("test/m")
    assert view is not None and view.retries_rate_limit == 1
    assert set(throughput_snapshot().keys()) == {"test/m"}


def test_reset_run_registries_clears_registry() -> None:
    from inspect_ai._control.eval_state import reset_run_registries

    record_generate("test/m", _usage())
    assert throughput_snapshot()
    reset_run_registries()
    assert throughput_snapshot() == {}


def test_throughput_report_envelope() -> None:
    record_generate("test/m", _usage(output_tokens=60, total_tokens=90))
    record_retry("test/m", "rate_limit")
    report = throughput_report(window=60)
    assert report["window_seconds"] == 60
    assert report["as_of"]
    (row,) = report["models"]
    assert row["model"] == "test/m"
    # per-row effective window: clamped to time-since-first-activity, so a
    # just-created record reports a window far below the requested one
    assert 0 < row["window_seconds"] <= report["window_seconds"]
    assert row["cumulative"]["requests"] == 1
    assert row["cumulative"]["retries"] == {"rate_limit": 1, "transient": 0}
    assert row["cumulative"]["first_activity_at"]


def test_footer_rate_gated_on_retries() -> None:
    # tokens alone leave the footer quiet
    record_generate("test/m", _usage(output_tokens=60))
    assert throughput_footer_rate() is None
    # a retry (on any model) opens the gate; rate aggregates across models
    record_retry("test/m", "rate_limit")
    rate = throughput_footer_rate()
    assert rate is not None and rate > 0


# ---------------------------------------------------------------------------
# Instrumentation feeds
# ---------------------------------------------------------------------------


async def test_generate_records_into_registry() -> None:
    model = get_model("mockllm/model")
    await model.generate("hello")
    view = throughput_view("mockllm/model")
    assert view is not None
    assert view.requests == 1
    assert view.total_tokens > 0


async def test_cache_hit_does_not_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # guard the cache-hit early return in Model._generate: a cached read
    # consumes no provider capacity and must not inflate the reported rate
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    model = get_model("mockllm/model")
    await model.generate("cache me", cache=True)
    view = throughput_view("mockllm/model")
    assert view is not None and view.requests == 1
    await model.generate("cache me", cache=True)
    view = throughput_view("mockllm/model")
    assert view is not None and view.requests == 1


def test_retry_waits_active_excludes_elapsed_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ActiveSample.retry_wait is cleared only when the whole retried call
    # resolves, not when its sleep elapses — a stale record (deadline in the
    # past, next attempt actively generating) must not count as "in backoff"
    import inspect_ai.log._samples as samples_mod
    from inspect_ai.log._samples import ActiveSampleRetryWait

    def wait(deadline_offset: float) -> Any:
        now = datetime.now(timezone.utc).timestamp()
        return SimpleNamespace(
            retry_wait=ActiveSampleRetryWait(
                model="m",
                attempt=1,
                started_at=now - 30.0,
                deadline=now + deadline_offset,
                qualified_model="test/m",
            )
        )

    monkeypatch.setattr(
        samples_mod,
        "active_samples",
        lambda: [wait(60.0), wait(-60.0), SimpleNamespace(retry_wait=None)],
    )
    record_retry("test/m", "rate_limit")
    view = throughput_view("test/m")
    assert view is not None
    assert view.retry_waits_active == 1


async def test_retry_config_records_retry_wait() -> None:
    config = model_retry_config(
        "m",
        None,
        None,
        lambda ex: True,
        lambda ex: None,
        lambda name, rs: None,
        qualified_model_name="test/m",
    )
    state = RetryCallState(cast(Any, None), None, (), {})
    state.upcoming_sleep = 42.0
    result = config["before_sleep"](state)
    assert result is not None
    await result
    view = throughput_view("test/m")
    assert view is not None
    assert view.retry_wait_seconds == pytest.approx(42.0)
    assert view.backoff_ratio > 0


async def test_retry_config_without_qualified_name_records_nothing() -> None:
    config = model_retry_config(
        "m",
        None,
        None,
        lambda ex: True,
        lambda ex: None,
        lambda name, rs: None,
    )
    state = RetryCallState(cast(Any, None), None, (), {})
    state.upcoming_sleep = 42.0
    result = config["before_sleep"](state)
    assert result is not None
    await result
    assert throughput_snapshot() == {}
