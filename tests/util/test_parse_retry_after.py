"""Tests for parse_retry_after()."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from inspect_ai._util.http import parse_retry_after


def test_retry_after_delta_seconds() -> None:
    assert parse_retry_after({"Retry-After": "30"}) == 30.0
    assert parse_retry_after({"retry-after": "1.5"}) == 1.5


def test_retry_after_http_date() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=45)
    header = format_datetime(future, usegmt=True)
    seconds = parse_retry_after({"Retry-After": header})
    assert seconds is not None
    assert 30 < seconds <= 45


def test_retry_after_negative_returns_none() -> None:
    assert parse_retry_after({"Retry-After": "-5"}) is None
    assert parse_retry_after({"Retry-After": "0"}) is None


def test_retry_after_unparseable_falls_through() -> None:
    # garbage in Retry-After but a valid reset header — should fall back
    headers = {
        "Retry-After": "not-a-date",
        "x-ratelimit-reset-requests": "20",
    }
    assert parse_retry_after(headers) == 20.0


def test_ratelimit_reset_delta_seconds() -> None:
    assert parse_retry_after({"x-ratelimit-reset-requests": "30"}) == 30.0


def test_ratelimit_reset_duration_string() -> None:
    # OpenAI-style duration shorthand
    assert parse_retry_after({"x-ratelimit-reset-requests": "1m30s"}) == 90.0
    assert parse_retry_after({"x-ratelimit-reset-requests": "500ms"}) == 0.5
    assert parse_retry_after({"x-ratelimit-reset-requests": "1.5s"}) == 1.5
    assert parse_retry_after({"x-ratelimit-reset-tokens": "2h"}) == 7200.0


def test_ratelimit_reset_iso_timestamp() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    header = future.isoformat().replace("+00:00", "Z")
    seconds = parse_retry_after({"x-ratelimit-reset-tokens": header})
    assert seconds is not None
    assert 50 < seconds <= 60


def test_ratelimit_reset_takes_larger_of_two() -> None:
    """Conservative cooldown picks the longer reset window.

    Without knowing which dimension triggered the 429, the longer reset is
    the safer floor for the next-cut debounce.
    """
    headers = {
        "x-ratelimit-reset-requests": "60",
        "x-ratelimit-reset-tokens": "20",
    }
    assert parse_retry_after(headers) == 60.0


def test_retry_after_wins_over_ratelimit_reset() -> None:
    # server is the authority on its own 429 — even if reset is smaller, honor Retry-After
    headers = {
        "Retry-After": "30",
        "x-ratelimit-reset-requests": "5",
    }
    assert parse_retry_after(headers) == 30.0


def test_no_relevant_headers_returns_none() -> None:
    assert parse_retry_after({}) is None
    assert parse_retry_after({"content-type": "application/json"}) is None


def test_case_insensitive_lookup() -> None:
    # headers may arrive with arbitrary case from different SDKs
    assert parse_retry_after({"RETRY-AFTER": "10"}) == 10.0
    assert parse_retry_after({"X-RateLimit-Reset-Requests": "15"}) == 15.0


def test_unparseable_reset_returns_none() -> None:
    assert parse_retry_after({"x-ratelimit-reset-requests": "garbage"}) is None


def test_naive_http_date_does_not_raise() -> None:
    """parsedate_to_datetime returns a naive datetime for HTTP-dates missing the GMT offset.

    Subtracting that from an aware now() would raise TypeError. We coerce to
    UTC and either return a positive seconds value or None.
    """
    # Malformed (no zone) but in the past → coerced to UTC, returns None for non-positive
    assert parse_retry_after({"Retry-After": "Wed, 21 Oct 1990 07:28:00"}) is None
    # Malformed but in the future → coerced to UTC, returns positive
    assert parse_retry_after({"Retry-After": "Wed, 21 Oct 2099 07:28:00"}) is not None


def test_ratelimit_reset_uses_max_not_min_when_multiple() -> None:
    """Conservative cooldown picks the largest of multiple reset windows.

    When requests and tokens both report reset times, we don't know which
    dimension triggered the 429, so use the *largest* reset to avoid
    prematurely cutting again.
    """
    headers = {
        "x-ratelimit-reset-requests": "10",
        "x-ratelimit-reset-tokens": "60",
    }
    assert parse_retry_after(headers) == 60.0


def test_anthropic_reset_headers_recognized() -> None:
    """Anthropic's own anthropic-ratelimit-*-reset family is a fallback signal.

    We should recognize it when Retry-After is absent.
    """
    # ISO timestamp ~30s in the future
    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    seconds = parse_retry_after({"anthropic-ratelimit-tokens-reset": future})
    assert seconds is not None
    assert 20 < seconds <= 30
