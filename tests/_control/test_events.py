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
from inspect_ai.log import EvalError, Transcript


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
    *,
    sample_uuid: str,
    events: list[Event],
    error_retries: list[Any],
    transcript: Transcript | None = None,
) -> Any:
    """A minimal stand-in for an in-flight ``ActiveSample``.

    Carries just what :func:`inspect_ai._control.events._running_source` reads:
    the ids, a real ``Transcript`` (so its ``history`` accessor — resident
    window, provider fallback — behaves exactly as in production), the durable
    ``sample_uuid``, and the ``error_retries`` whose length is the attempt
    count. Pass ``transcript`` to use a pre-built (eg. bounded) transcript
    instead of an unbounded one seeded with ``events``.
    """
    return SimpleNamespace(
        eval_id="e1",
        epoch=1,
        sample=SimpleNamespace(id=1),
        transcript=transcript if transcript is not None else Transcript(events),
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


# --- bounded transcripts (evicted events) -----------------------------------


def _bounded_running_sample(events: list[Event], *, with_provider: bool) -> Any:
    """A running sample on a bounded transcript (resident tail of 3).

    With ``with_provider`` the full history is recoverable (the production
    shape — the provider is the realtime sample buffer); without it, evicted
    events are gone for good.
    """
    from test_helpers.transcript import FakeTranscriptHistoryProvider

    provider = FakeTranscriptHistoryProvider(events) if with_provider else None
    transcript = Transcript(bounded=True, resident_tail=3, history_provider=provider)
    for event in events:
        transcript._event(event)
    assert transcript.history.resident_events_truncated  # sanity: head evicted
    return _fake_running_sample(
        sample_uuid="u1", events=[], error_retries=[], transcript=transcript
    )


async def test_cursor_below_resident_window_pages_via_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evicted events are served from the history provider, gap-free.

    A bounded transcript keeps only a resident tail in memory; a read from
    the beginning (or a cursor below the resident window) must page through
    the evicted span via the provider — not skip it.
    """
    import inspect_ai.log._samples as samples_mod

    events: list[Event] = [_info_at(f"e{i}", _now()) for i in range(10)]
    sample = _bounded_running_sample(events, with_provider=True)
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [sample])

    # page from the beginning in pages smaller than the evicted span
    page1 = await sample_events("e1", "1", 1, limit=4)
    assert page1 is not None
    assert [e["source"] for e in page1["events"]] == ["e0", "e1", "e2", "e3"]

    page2 = await sample_events("e1", "1", 1, since=page1["next"], limit=4)
    assert page2 is not None
    assert [e["source"] for e in page2["events"]] == ["e4", "e5", "e6", "e7"]

    page3 = await sample_events("e1", "1", 1, since=page2["next"], limit=4)
    assert page3 is not None
    assert [e["source"] for e in page3["events"]] == ["e8", "e9"]


async def test_tail_beyond_resident_window_served_via_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--tail N` larger than the resident window reads back through the provider."""
    import inspect_ai.log._samples as samples_mod

    events: list[Event] = [_info_at(f"e{i}", _now()) for i in range(10)]
    sample = _bounded_running_sample(events, with_provider=True)
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [sample])

    page = await sample_events("e1", "1", 1, tail=8)
    assert page is not None
    assert [e["source"] for e in page["events"]] == [f"e{i}" for i in range(2, 10)]


async def test_evicted_events_without_provider_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading an evicted range with no provider errors rather than gapping.

    Bounded-without-provider doesn't occur in production (`_sample_transcript_
    config` only enables bounded mode when the buffer DB exists), so there's no
    soft "missed N" signal — a hard error (the endpoint surfaces it as a
    structured 500) beats serving a silently-gapped stream. Reads within the
    resident window still work.
    """
    import inspect_ai.log._samples as samples_mod

    events: list[Event] = [_info_at(f"e{i}", _now()) for i in range(10)]
    sample = _bounded_running_sample(events, with_provider=False)
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [sample])

    with pytest.raises(RuntimeError, match="not available"):
        await sample_events("e1", "1", 1)

    # the resident window itself remains readable
    page = await sample_events("e1", "1", 1, tail=3)
    assert page is not None
    assert [e["source"] for e in page["events"]] == ["e7", "e8", "e9"]


# --- streaming-buffer events (event-less recorder sample) -------------------


async def test_buffer_served_events_are_materialized(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Events served from the buffer database are fully materialized.

    The `.eval` streaming-completion path retains an event-less sample in the
    recorder (its events live in the buffer database), so the events page is
    served from the buffer. Reading the raw buffer rows exposed condensed
    events — `input_refs` / `call_refs` pointing into pools that weren't
    returned, and unresolved attachments. The buffer read now goes through
    `BufferTranscriptHistoryProvider` (the same materialization as live
    transcript and finalized log reads), so pooled refs are re-expanded into
    real messages.
    """
    import inspect_ai._control.state as state_mod
    import inspect_ai.log._recorders.buffer.database as database_mod
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
    from inspect_ai.log._recorders.types import SampleEvent
    from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput

    monkeypatch.setattr(
        database_mod, "resolve_db_dir", lambda db_dir=None: db_dir or tmp_path
    )
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    location = str(tmp_path / "logs" / "task.eval")
    db = SampleBufferDatabase(location)
    event = ModelEvent(
        uuid="ev-1",
        model="mockllm/model",
        input=[ChatMessageUser(id="m1", content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "answer"),
    )
    db.log_events([SampleEvent(id="s1", epoch=1, event=event)])
    try:
        register_eval("e1", 1, log_location=location)

        # the streaming-path shape: the resolved sample carries no events
        async def event_less_sample(
            eval_id: str, sample_id: str, epoch: int, *, exclude_fields: Any = None
        ) -> Any:
            return SimpleNamespace(
                events=[], id="s1", uuid="u1", epoch=1, error_retries=[]
            )

        monkeypatch.setattr(state_mod, "_full_sample", event_less_sample)

        page = await sample_events("e1", "s1", 1, full=True)
        assert page is not None
        [model] = page["events"]
        assert model["event"] == "model"
        # pooled input refs are re-expanded into real messages...
        assert model["input"] and model["input"][0]["content"] == "question"
        # ...not left as condensed refs into pools the page doesn't carry
        assert not model.get("input_refs")
        assert model["output"]["choices"][0]["message"]["content"] == "answer"
    finally:
        clear_all_eval_states()
        db.cleanup()
