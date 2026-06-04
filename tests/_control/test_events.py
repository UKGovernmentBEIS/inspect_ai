"""Unit tests for the control-channel per-sample events helpers.

The cursor encode/decode, the type/time filter, and the compact projection are
pure functions over `Event`s — exercised here directly. The end-to-end
`sample_events` (live transcript / on-disk log + cursor paging) is covered by
the integration tests in `test_eval_set_integration.py`.
"""

from datetime import datetime, timedelta, timezone

from inspect_ai._control.events import (
    HIGH_SIGNAL_EVENT_TYPES,
    _filter,
    _project,
    decode_cursor,
    encode_cursor,
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
