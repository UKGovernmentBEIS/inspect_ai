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
from test_helpers.live_eval_data import FakeLiveEvalData

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


# --- tail seeding ----------------------------------------------------------


def _span_begin(i: int) -> Event:
    from inspect_ai.event._span import SpanBeginEvent

    return SpanBeginEvent(id=f"span-{i}", name=f"span{i}")


async def test_tail_counts_matched_events_not_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tail seed returns the last N events *matching the filter*.

    A live transcript is dominated by structural events (state / store /
    span), so slicing the raw sequence by ``tail`` could render a single
    high-signal event (plus a cursor) even though more matches sat just below
    the raw window — a near-empty default page for exactly the "what is this
    sample doing?" read (issue #162).
    """
    import inspect_ai.log._samples as samples_mod

    # two high-signal events buried under a pile of trailing structural ones:
    # a raw-event tail of 5 contains zero matches
    events: list[Event] = [
        _info_at("first", _now()),
        _info_at("second", _now()),
        *[_span_begin(i) for i in range(10)],
    ]
    sample = _fake_running_sample(sample_uuid="u1", events=events, error_retries=[])
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [sample])

    page = await sample_events("e1", "1", 1, tail=5)
    assert page is not None
    assert [e["source"] for e in page["events"]] == ["first", "second"]
    # the cursor still advances past everything scanned (raw offset)
    assert decode_cursor(page["next"]) == ("u1:0", len(events))


async def test_tail_keeps_only_most_recent_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With more matches than ``tail``, the page is the most recent ones."""
    import inspect_ai.log._samples as samples_mod

    # matches interleaved with structural events
    events: list[Event] = []
    for i in range(6):
        events.append(_info_at(f"m{i}", _now()))
        events.append(_span_begin(i))
    sample = _fake_running_sample(sample_uuid="u1", events=events, error_retries=[])
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [sample])

    page = await sample_events("e1", "1", 1, tail=2)
    assert page is not None
    assert [e["source"] for e in page["events"]] == ["m4", "m5"]


async def test_tail_scan_is_page_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The matched-tail scan reaches back at most ``limit`` events.

    A match sitting below the trailing ``limit``-sized window stays out of the
    page — the tail seed keeps the same per-page scan bound as every other
    read rather than walking the whole backlog hunting for matches.
    """
    import inspect_ai.log._samples as samples_mod

    events: list[Event] = [
        _info_at("early", _now()),
        *[_span_begin(i) for i in range(10)],
    ]
    sample = _fake_running_sample(sample_uuid="u1", events=events, error_retries=[])
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [sample])

    page = await sample_events("e1", "1", 1, tail=5, limit=10)
    assert page is not None
    assert page["events"] == []  # the only match sits below the scan window
    # `next` still lands at the end of the scanned window
    assert decode_cursor(page["next"]) == ("u1:0", len(events))


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


def test_filter_all_includes_everything() -> None:
    # `all` is the shell-safe synonym for `*` — same allow-everything filter,
    # including as one member of a comma list
    events: list[Event] = [_info_at("a", _now()), _error_event("boom")]
    assert len(_filter(events, frozenset({"all"}), None, None)) == 2
    assert len(_filter(events, frozenset({"model", "all"}), None, None)) == 2


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
    out = _project(_error_event("boom"), content=True, full=False)
    assert out["event"] == "error"
    assert out["error"] == "boom"
    assert isinstance(out["timestamp"], float)
    assert "uuid" in out and "span_id" in out


def test_project_compact_info_carries_data() -> None:
    # transcript().info(...) content must be visible with --content: the
    # compact projection carries the (truncated, text-form) data payload.
    out = _project(
        InfoEvent(source="my-solver", data="phase 1 complete"),
        content=True,
        full=False,
    )
    assert out["event"] == "info"
    assert out["source"] == "my-solver"
    assert out["data"] == "phase 1 complete"
    # non-string data is serialized to text
    out = _project(InfoEvent(data={"step": 2}), content=True, full=False)
    assert out["source"] is None
    assert out["data"] == '{"step": 2}'
    # long payloads are truncated, not dumped whole
    out = _project(InfoEvent(data="x" * 1000), content=True, full=False)
    assert len(out["data"]) <= 256


def test_project_metadata_default_withholds_free_text() -> None:
    """Without ``content`` the projection is metadata only.

    No field the evaluated agent controls (error messages, info data) is
    present, while the structural header and error *presence* remain readable.
    """
    out = _project(_error_event("boom"), content=False, full=False)
    assert out["event"] == "error"
    assert "error" not in out
    assert isinstance(out["timestamp"], float)

    out = _project(
        InfoEvent(source="my-solver", data="agent-controlled"),
        content=False,
        full=False,
    )
    assert out["source"] == "my-solver"
    assert "data" not in out


def test_project_metadata_default_tool_event() -> None:
    from inspect_ai.event._tool import ToolEvent
    from inspect_ai.tool._tool_call import ToolCallError

    event = ToolEvent(
        id="t1",
        function="bash",
        arguments={"cmd": "echo payload"},
        result="payload",
        error=ToolCallError(type="unknown", message="boom"),
    )
    out = _project(event, content=False, full=False)
    assert out["function"] == "bash"
    assert out["has_error"] is True
    assert "arguments" not in out and "result" not in out and "error" not in out

    out = _project(event, content=True, full=False)
    assert "echo payload" in out["arguments"]
    assert out["result"] == "payload"
    assert out["error"] == "boom"
    assert out["has_error"] is True


def test_project_full_is_raw_dump() -> None:
    out = _project(_error_event("boom"), content=False, full=True)
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


# --- terminal-source cache ---------------------------------------------------


def _counting_terminal_sample(
    monkeypatch: pytest.MonkeyPatch,
    events: list[Event],
    *,
    error_retries: list[Any] | None = None,
) -> list[int]:
    """Route `_full_sample` to a fixed terminal sample, counting resolutions.

    Returns a single-element list holding the resolution count, so tests can
    assert how many times the (expensive, per-request in the uncached design)
    full-sample read actually ran.
    """
    import inspect_ai._control.state as state_mod
    import inspect_ai.log._samples as samples_mod

    reads = [0]
    retries = error_retries or []

    async def full_sample(
        eval_id: str, sample_id: str, epoch: int, *, exclude_fields: Any = None
    ) -> Any:
        reads[0] += 1
        return SimpleNamespace(
            events=events, id="s1", uuid="u1", epoch=1, error_retries=retries
        )

    monkeypatch.setattr(state_mod, "_full_sample", full_sample)
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])
    return reads


async def test_terminal_source_resolved_once_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paginating a flushed sample parses it once, not once per page.

    The uncached design re-read and re-validated the entire sample per page
    request — O(N²/limit) aggregate work for an N-event transcript — and per
    poll, even though a finished sample never has new events.
    """
    events: list[Event] = [_info_at(f"e{i}", _now()) for i in range(5)]
    reads = _counting_terminal_sample(monkeypatch, events)

    page1 = await sample_events("e1", "s1", 1, limit=2)
    assert page1 is not None
    assert [e["source"] for e in page1["events"]] == ["e0", "e1"]

    page2 = await sample_events("e1", "s1", 1, since=page1["next"], limit=2)
    assert page2 is not None
    assert [e["source"] for e in page2["events"]] == ["e2", "e3"]

    page3 = await sample_events("e1", "s1", 1, since=page2["next"], limit=2)
    assert page3 is not None
    assert [e["source"] for e in page3["events"]] == ["e4"]
    assert page3["done"]

    # one resolution served all three pages (and any subsequent poll)
    assert reads[0] == 1


async def test_terminal_source_cache_expires_and_hits_do_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry expires TTL after *insertion* — a hit doesn't extend its life.

    This is the staleness bound: a steady poller (whose hits would otherwise
    keep an entry alive forever) still re-resolves at least once per TTL.
    """
    import inspect_ai._control.events as events_mod
    from inspect_ai._control.terminal_cache import TerminalSourceCache

    now = {"t": 0.0}
    monkeypatch.setattr(
        events_mod,
        "_terminal_sources",
        TerminalSourceCache(ttl=5.0, clock=lambda: now["t"]),
    )
    events: list[Event] = [_info_at("e0", _now())]
    reads = _counting_terminal_sample(monkeypatch, events)

    assert await sample_events("e1", "s1", 1) is not None  # resolve + cache
    now["t"] = 3.0
    assert await sample_events("e1", "s1", 1) is not None  # within TTL: a hit
    assert reads[0] == 1

    # 6s after insertion (though only 3s after the last hit) — expired
    now["t"] = 6.0
    assert await sample_events("e1", "s1", 1) is not None
    assert reads[0] == 2


async def test_running_attempt_invalidates_cached_terminal_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poll that observes a retry running drops the prior attempt's entry.

    Sequence: attempt 1 terminal (cached) → retry_on_error re-runs the sample
    (running source served) → retry terminal. The final read must serve the
    retry's transcript even though attempt 1's entry would still be within its
    TTL — resolving a running source invalidates the cached terminal source.
    """
    import inspect_ai._control.state as state_mod
    import inspect_ai.log._samples as samples_mod

    # attempt 1 flushed: resolved and cached
    reads = _counting_terminal_sample(monkeypatch, [_info_at("attempt1", _now())])
    page = await sample_events("e1", "1", 1)
    assert page is not None
    assert [e["source"] for e in page["events"]] == ["attempt1"]
    assert reads[0] == 1

    # the retry is observed running: served live, and the stale entry dropped
    retrying = _fake_running_sample(
        sample_uuid="u1",
        events=[_info_at("retrying", _now())],
        error_retries=[object()],
    )
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [retrying])
    page = await sample_events("e1", "1", 1)
    assert page is not None
    assert [e["source"] for e in page["events"]] == ["retrying"]

    # the retry finishes and is flushed: its own transcript is served, not
    # attempt 1's still-within-TTL entry
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    async def retry_sample(
        eval_id: str, sample_id: str, epoch: int, *, exclude_fields: Any = None
    ) -> Any:
        return SimpleNamespace(
            events=[_info_at("attempt2", _now())],
            id="s1",
            uuid="u1",
            epoch=1,
            error_retries=[object()],
        )

    monkeypatch.setattr(state_mod, "_full_sample", retry_sample)
    page = await sample_events("e1", "1", 1)
    assert page is not None
    assert [e["source"] for e in page["events"]] == ["attempt2"]


async def test_running_attempt_invalidates_other_endpoints_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observing a retry on one endpoint drops the key from *every* cache.

    A retry supersedes the prior attempt's terminal source in both
    projections, so an events poll that observes it running must invalidate
    the messages cache too (and vice versa) — otherwise a messages request
    within the TTL would still serve the prior attempt's conversation.
    """
    import inspect_ai._control.events as events_mod
    import inspect_ai._control.messages as messages_mod
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.messages import MessagesSource

    key = ("e1", "1", 1)
    messages_mod._terminal_sources.put(
        key, MessagesSource(messages=[], status="completed")
    )

    running = _fake_running_sample(
        sample_uuid="u1",
        events=[_info_at("retrying", _now())],
        error_retries=[object()],
    )
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [running])
    assert await sample_events("e1", "1", 1) is not None

    assert messages_mod._terminal_sources.get(key) is None
    assert events_mod._terminal_sources.get(key) is None


def test_terminal_source_cache_evicts_oldest_when_full() -> None:
    """The entry cap evicts oldest-inserted first (memory bound, not LRU)."""
    from inspect_ai._control.terminal_cache import TerminalSourceCache

    cache: TerminalSourceCache[str] = TerminalSourceCache(
        ttl=100.0, max_entries=2, clock=lambda: 0.0
    )
    cache.put(("e", "a", 1), "a")
    cache.put(("e", "b", 1), "b")
    cache.put(("e", "c", 1), "c")
    assert cache.get(("e", "a", 1)) is None
    assert cache.get(("e", "b", 1)) == "b"
    assert cache.get(("e", "c", 1)) == "c"


# --- streaming-buffer events (event-less recorder sample) -------------------


def _register_buffered_eval(db: Any, location: str) -> None:
    """Register an eval whose ``live.sample_events_provider`` pages the buffer db.

    Mirrors production, where the control layer calls
    ``EvalState.live.sample_events_provider`` (i.e. ``TaskLogger``'s method),
    which builds a ``BufferTranscriptHistoryProvider`` over the eval's own
    buffer instance.
    """
    from inspect_ai._control.eval_state import register_eval
    from inspect_ai.log._recorders.buffer.transcript_history_provider import (
        BufferTranscriptHistoryProvider,
    )

    register_eval(
        "e1",
        1,
        log_location=location,
        live=FakeLiveEvalData(
            events=lambda id, epoch: BufferTranscriptHistoryProvider(db, id, epoch)
        ),
    )


def _event_less_sample_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `_full_sample` resolve to the streaming-path event-less sample."""
    import inspect_ai._control.state as state_mod
    import inspect_ai.log._samples as samples_mod

    async def event_less_sample(
        eval_id: str, sample_id: str, epoch: int, *, exclude_fields: Any = None
    ) -> Any:
        return SimpleNamespace(events=[], id="s1", uuid="u1", epoch=1, error_retries=[])

    monkeypatch.setattr(state_mod, "_full_sample", event_less_sample)
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])


async def test_buffer_served_events_are_materialized(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Events served from the buffer are fully materialized.

    The `.eval` streaming-completion path retains an event-less sample in the
    recorder (its events live in the buffer database), so the events page is
    served through the eval's registered events provider. Reading raw buffer
    rows exposed condensed events — `input_refs` / `call_refs` pointing into
    pools that weren't returned, and unresolved attachments. The provider path
    (the same materialization as live transcript and finalized log reads)
    re-expands pooled refs into real messages.
    """
    from inspect_ai._control.eval_state import clear_all_eval_states
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
    from inspect_ai.log._recorders.types import SampleEvent
    from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput

    location = str(tmp_path / "logs" / "task.eval")
    db = SampleBufferDatabase(location, db_dir=tmp_path)
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
        _register_buffered_eval(db, location)
        _event_less_sample_stub(monkeypatch)

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


async def test_buffer_served_events_page_through_the_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Buffer-served pages read page-sized via the provider, not all-at-once.

    The page limit must ride down to the provider's `events_from` (and from
    there to the buffer query) — paging a long finished transcript must not
    re-materialize the full history per request.
    """
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
    from inspect_ai.log._recorders.buffer.transcript_history_provider import (
        BufferTranscriptHistoryProvider,
    )
    from inspect_ai.log._recorders.types import SampleEvent

    location = str(tmp_path / "logs" / "task.eval")
    db = SampleBufferDatabase(location, db_dir=tmp_path)
    db.log_events(
        [
            SampleEvent(id="s1", epoch=1, event=InfoEvent(uuid=f"ev-{i}", data=i))
            for i in range(5)
        ]
    )

    calls: list[tuple[int, int | None]] = []

    class CapturingProvider(BufferTranscriptHistoryProvider):
        def events_from(self, start: int, limit: int | None = None) -> Any:
            calls.append((start, limit))
            return super().events_from(start, limit)

    try:
        register_eval(
            "e1",
            1,
            log_location=location,
            live=FakeLiveEvalData(
                events=lambda id, epoch: CapturingProvider(db, id, epoch)
            ),
        )
        _event_less_sample_stub(monkeypatch)

        page1 = await sample_events("e1", "s1", 1, limit=2)
        assert page1 is not None and not page1["done"]
        assert [e["event"] for e in page1["events"]] == ["info", "info"]

        page2 = await sample_events("e1", "s1", 1, since=page1["next"], limit=2)
        assert page2 is not None and not page2["done"]

        page3 = await sample_events("e1", "s1", 1, since=page2["next"], limit=2)
        assert page3 is not None and page3["done"]
        assert len(page3["events"]) == 1

        # each request was one page-sized provider read
        assert calls == [(0, 2), (2, 2), (4, 2)]
    finally:
        clear_all_eval_states()
        db.cleanup()


async def test_buffer_torn_down_before_read_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A buffer teardown racing the read degrades to the recorder's events.

    The eval can tear the buffer down while a control request is in flight.
    Whether the provider factory already returns None (buffer gone) or the
    first provider read fails (deletion landed between resolution and read),
    the page must degrade like "no buffer" — empty events from the event-less
    recorder sample — rather than surface a 500.
    """
    from test_helpers.transcript import FakeTranscriptHistoryProvider

    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log import TranscriptHistoryUnavailableError

    _event_less_sample_stub(monkeypatch)

    class TornDownProvider(FakeTranscriptHistoryProvider):
        def __init__(self) -> None:
            super().__init__([])

        @property
        def event_count(self) -> int:
            raise TranscriptHistoryUnavailableError("history store torn down")

    try:
        # deletion landed between provider resolution and the first read
        register_eval(
            "e1", 1, live=FakeLiveEvalData(events=lambda id, epoch: TornDownProvider())
        )
        page = await sample_events("e1", "s1", 1)
        assert page is not None, "teardown race must degrade, not 404/500"
        assert page["events"] == []  # recorder sample is event-less
        assert page["done"]
    finally:
        clear_all_eval_states()

    try:
        # buffer already torn down: the factory itself returns None
        register_eval("e1", 1, live=FakeLiveEvalData(events=lambda id, epoch: None))
        page = await sample_events("e1", "s1", 1)
        assert page is not None
        assert page["events"] == []
    finally:
        clear_all_eval_states()


async def test_buffer_torn_down_between_count_and_fetch_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A teardown landing after event_count but before the page fetch degrades.

    The two provider reads happen at different points in the request; the
    fetch must get the same degrade contract as the count — a short (empty)
    page with `done` still false (next doesn't advance), so the client's
    retry re-resolves the source rather than the request 500ing.
    """
    from test_helpers.transcript import FakeTranscriptHistoryProvider

    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log import TranscriptHistoryUnavailableError

    _event_less_sample_stub(monkeypatch)

    class TornDownAfterCount(FakeTranscriptHistoryProvider):
        def __init__(self) -> None:
            super().__init__([])

        @property
        def event_count(self) -> int:
            return 3  # buffer still present at count time

        def events_from(self, start: int, limit: int | None = None) -> Any:
            raise TranscriptHistoryUnavailableError("history store torn down")

    try:
        register_eval(
            "e1",
            1,
            live=FakeLiveEvalData(events=lambda id, epoch: TornDownAfterCount()),
        )
        page = await sample_events("e1", "s1", 1)
        assert page is not None, "teardown race must degrade, not 404/500"
        assert page["events"] == []
        assert not page["done"]  # short page: the client retries
    finally:
        clear_all_eval_states()
