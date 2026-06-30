"""Tests for format_traceback caching (issue #4316)."""
import sys
import time

import pytest

from inspect_ai._util.rich import _traceback_cache, format_traceback


def _make_exc() -> tuple:
    try:
        raise ConnectionError("API timeout: model endpoint unreachable")
    except ConnectionError:
        return sys.exc_info()


def setup_function() -> None:
    _traceback_cache.clear()


def test_format_traceback_returns_text_and_ansi() -> None:
    exc_type, exc_value, exc_tb = _make_exc()
    text, ansi = format_traceback(exc_type, exc_value, exc_tb)
    assert "ConnectionError" in text
    assert "ConnectionError" in ansi


def test_format_traceback_caches_repeated_calls() -> None:
    exc_type, exc_value, exc_tb = _make_exc()

    # First call: renders and populates cache
    t0 = time.perf_counter()
    format_traceback(exc_type, exc_value, exc_tb)
    first_ms = (time.perf_counter() - t0) * 1000

    # Subsequent calls: should be cache hits — at least 10x faster
    times = []
    for _ in range(49):
        t0 = time.perf_counter()
        format_traceback(exc_type, exc_value, exc_tb)
        times.append((time.perf_counter() - t0) * 1000)

    avg_subsequent_ms = sum(times) / len(times)
    assert avg_subsequent_ms < first_ms / 10, (
        f"Cache not working: first={first_ms:.2f}ms avg_subsequent={avg_subsequent_ms:.2f}ms"
    )


def test_format_traceback_cache_keyed_by_traceback_text() -> None:
    try:
        raise ValueError("error A")
    except ValueError:
        exc_a = sys.exc_info()

    try:
        raise RuntimeError("error B")
    except RuntimeError:
        exc_b = sys.exc_info()

    text_a, ansi_a = format_traceback(*exc_a)
    text_b, ansi_b = format_traceback(*exc_b)

    # Different errors produce different results
    assert text_a != text_b
    assert ansi_a != ansi_b
    # Both cached separately
    assert len(_traceback_cache) == 2


def test_format_traceback_same_result_on_cache_hit() -> None:
    exc_type, exc_value, exc_tb = _make_exc()
    result1 = format_traceback(exc_type, exc_value, exc_tb)
    result2 = format_traceback(exc_type, exc_value, exc_tb)
    assert result1 == result2
