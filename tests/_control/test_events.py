"""Unit tests for the control-channel per-sample events helpers.

The cursor encode/decode, the type/time filter, and the compact projection are
pure functions over `Event`s — exercised here directly. The end-to-end
`sample_events` (live transcript / on-disk log + cursor paging) is covered by
the integration tests in `test_eval_set_integration.py`.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from inspect_ai._control.events import (
    HIGH_SIGNAL_EVENT_TYPES,
    _attempt_nonce,
    _filter,
    _project,
    decode_cursor,
    encode_cursor,
    sample_events,
)
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.log import EvalError


def _error_event(message: str) -> ErrorEvent:
    return ErrorEvent(error=EvalError(message=message, traceback="", traceback_ansi=""))


def _info_at(source: str, ts: datetime) -> InfoEvent:
    e = InfoEvent(source=source, data="x")
    e.timestamp = ts
    return e


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- cursor ---------------------------------------------------------------


def test_cursor_roundtrips() -> None:
    assert decode_cursor(encode_cursor("nonce-1", 42)) == ("nonce-1", 42)
    assert decode_cursor(encode_cursor("a:b:c", 0)) == ("a:b:c", 0)


def test_cursor_missing_or_malformed_resets_to_start() -> None:
    # A missing / empty / garbage token decodes to "start from the beginning"
    # — a confused client just re-reads rather than erroring.
    assert decode_cursor(None) == (None, 0)
    assert decode_cursor("") == (None, 0)
    assert decode_cursor("not-valid-base64!!") == (None, 0)
    assert decode_cursor("YWJj") == (None, 0)  # valid base64, not our JSON shape


# --- attempt nonce --------------------------------------------------------


def test_attempt_nonce_distinguishes_retry_attempts() -> None:
    # retry_on_error reuses the sample uuid on a fresh transcript; the attempt
    # count (prior failed attempts, read off error_retries) must make the nonce
    # differ so a stale attempt-1 cursor isn't applied to attempt 2's transcript.
    first = _attempt_nonce("uuid-1", 1, 1, 0)
    second = _attempt_nonce("uuid-1", 1, 1, 1)
    assert first != second
    # the running and terminal views of the *same* attempt derive it identically
    assert _attempt_nonce("uuid-1", 1, 1, 1) == second


def test_attempt_nonce_fallback_is_stable_and_attempt_distinct() -> None:
    # uuid-less fallback (a pre-uuid sample from an old on-disk log) is still a
    # stable, attempt-distinct nonce.
    assert _attempt_nonce(None, 7, 2, 0) == _attempt_nonce(None, 7, 2, 0)
    assert _attempt_nonce(None, 7, 2, 0) != _attempt_nonce(None, 7, 2, 1)


# --- retry_on_error cursor reuse ------------------------------------------


def _fake_running_sample(
    *, sample_uuid: str, events: list[Event], error_retries: list[Any]
) -> Any:
    """A minimal stand-in for an in-flight ``ActiveSample``.

    Carries just what :func:`inspect_ai._control.events._running_source` reads:
    the ids, the transcript event window, the durable ``sample_uuid``, and the
    ``error_retries`` whose length is the attempt count.
    """
    history = SimpleNamespace(event_count=len(events), resident_events=events)
    return SimpleNamespace(
        eval_id="e1",
        epoch=1,
        sample=SimpleNamespace(id=1),
        transcript=SimpleNamespace(history=history),
        sample_uuid=sample_uuid,
        error_retries=error_retries,
        completed=None,
    )


async def test_retry_on_error_cursor_does_not_skip_fresh_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cursor from a failed attempt must not skip the retry's fresh transcript.

    ``retry_on_error`` re-runs a sample on a brand-new transcript while reusing
    ``state.uuid``. A cursor handed out during attempt 1 (its offset indexes
    attempt 1's events) must not be honored against attempt 2's unrelated, often
    shorter transcript — that silently skipped the retry's events. The attempt
    count in the nonce makes the stale cursor mismatch and restart from 0.
    """
    import inspect_ai.log._samples as samples_mod

    # attempt 1: three events, no prior failures (attempt count 0)
    attempt1 = _fake_running_sample(
        sample_uuid="uuid-1",
        events=[_info_at(f"a{i}", _now()) for i in range(3)],
        error_retries=[],
    )
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [attempt1])
    page = await sample_events("e1", "1", 1)
    assert page is not None and len(page["events"]) == 3
    attempt1_cursor = page["next"]  # nonce = uuid-1:0, offset = 3

    # attempt 2: a fresh, shorter transcript under the same uuid, one prior
    # failed attempt (attempt count 1)
    attempt2 = _fake_running_sample(
        sample_uuid="uuid-1",
        events=[_info_at("retry", _now())],
        error_retries=[object()],
    )
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [attempt2])
    resumed = await sample_events("e1", "1", 1, since=attempt1_cursor)

    # the stale cursor is rejected (different attempt nonce) and the read
    # restarts from 0, so the retry's event is delivered — not skipped (the bug
    # applied offset 3 to the 1-event transcript and returned nothing).
    assert resumed is not None
    assert [e["source"] for e in resumed["events"]] == ["retry"]


# --- type filter ----------------------------------------------------------


def test_filter_default_is_high_signal() -> None:
    assert "error" in HIGH_SIGNAL_EVENT_TYPES and "info" in HIGH_SIGNAL_EVENT_TYPES
    events: list[Event] = [_info_at("a", _now()), _error_event("boom")]
    assert [e.event for e in _filter(events, None, None, None)] == ["info", "error"]


def test_filter_restricts_to_named_types() -> None:
    events: list[Event] = [_info_at("a", _now()), _error_event("boom")]
    out = _filter(events, frozenset({"error"}), None, None)
    assert [e.event for e in out] == ["error"]


def test_filter_glob_includes_everything() -> None:
    # even a type outside the high-signal tier passes with '*'
    events: list[Event] = [_info_at("a", _now()), _error_event("boom")]
    assert len(_filter(events, frozenset({"*"}), None, None)) == 2


def test_filter_time_window() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    early = _info_at("early", t0)
    late = _info_at("late", t0 + timedelta(seconds=10))
    events: list[Event] = [early, late]
    mid = (t0 + timedelta(seconds=5)).timestamp()
    assert _filter(events, None, mid, None) == [late]  # since_time → only late
    assert _filter(events, None, None, mid) == [early]  # until → only early


# --- projection -----------------------------------------------------------


def test_project_compact_error() -> None:
    out = _project(_error_event("boom"), full=False)
    assert out["event"] == "error"
    assert out["error"] == "boom"
    assert isinstance(out["timestamp"], float)
    assert "uuid" in out and "span_id" in out


def test_project_full_is_raw_dump() -> None:
    out = _project(_error_event("boom"), full=True)
    assert out["event"] == "error"
    # raw form keeps the nested EvalError object, not the flattened message
    assert isinstance(out["error"], dict)
    assert out["error"]["message"] == "boom"
