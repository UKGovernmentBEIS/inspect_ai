"""Phase 7 unit tests: TUI Inspect-native event-chip rendering.

Covers:

- :meth:`SessionState.consume_sample_limit_event` /
  :meth:`SessionState.consume_error_event` /
  :meth:`SessionState.consume_compaction_event` /
  :meth:`SessionState.consume_info_event` each mint an
  :class:`EventChip` at the current end-of-transcript position with
  the expected ``kind`` / ``header_summary`` / ``body_text`` /
  ``traceback`` fields.
- The ``consume_inspect_event`` dispatcher routes the four new
  ``event`` discriminator values to the right builder.
- UUID-keyed dedup drops a second delivery of the same event so
  replay on reconnect doesn't double-mount.
- The :class:`ScoreChip` ``answer`` field is populated from the
  serialized ``score.answer`` when present.

The widget-rendering pilot lives in ``test_event_chip_widget.py``;
this module is the state-layer-only fast loop.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.agent._acp.tui.state import (
    EventChip,
    ScoreChip,
    SessionState,
    _classify_score_value,
    _format_info_data,
    _format_token_count,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wrap_uuid(event: dict[str, Any], uuid: str) -> dict[str, Any]:
    """Attach a stable uuid so the dedup set behaves under replay tests."""
    return {**event, "uuid": uuid}


def _sample_limit_payload(
    *,
    limit_type: str | None = "token",
    message: str | None = "ran out of tokens",
    limit: float | None = 1000.0,
) -> dict[str, Any]:
    """Build a serialized ``SampleLimitEvent`` as the wire would deliver it."""
    payload: dict[str, Any] = {"event": "sample_limit"}
    if limit_type is not None:
        payload["type"] = limit_type
    if message is not None:
        payload["message"] = message
    if limit is not None:
        payload["limit"] = limit
    return payload


def _error_payload(
    *,
    message: str | None = "ValueError: bad input",
    traceback: str | None = "Traceback…\n  File a.py, line 1\n    raise ValueError",
    traceback_ansi: str | None = None,
) -> dict[str, Any]:
    """Build a serialized ``ErrorEvent`` as the wire would deliver it."""
    error: dict[str, Any] = {}
    if message is not None:
        error["message"] = message
    if traceback is not None:
        error["traceback"] = traceback
    if traceback_ansi is not None:
        error["traceback_ansi"] = traceback_ansi
    return {"event": "error", "error": error}


def _compaction_payload(
    *,
    compaction_type: str | None = "summary",
    tokens_before: int | None = 12_345,
    tokens_after: int | None = 4_100,
    source: str | None = None,
) -> dict[str, Any]:
    """Build a serialized ``CompactionEvent`` as the wire would deliver it."""
    payload: dict[str, Any] = {"event": "compaction"}
    if compaction_type is not None:
        payload["type"] = compaction_type
    if tokens_before is not None:
        payload["tokens_before"] = tokens_before
    if tokens_after is not None:
        payload["tokens_after"] = tokens_after
    if source is not None:
        payload["source"] = source
    return payload


def _info_payload(
    *,
    source: str | None = "subsystem",
    data: Any = "subsystem ready",
) -> dict[str, Any]:
    """Build a serialized ``InfoEvent`` as the wire would deliver it."""
    payload: dict[str, Any] = {"event": "info", "data": data}
    if source is not None:
        payload["source"] = source
    return payload


# ---------------------------------------------------------------------------
# consume_sample_limit_event
# ---------------------------------------------------------------------------


def test_consume_sample_limit_event_renders_type_and_limit_with_message_body() -> None:
    """Header carries ``limit · <type> · <numeric>``; body carries the message.

    Sample-limit events are terminal — the message is the operator's
    only inline explanation of why the run stopped, so dropping it
    would force a transcript dive for what's a one-line answer.
    """
    state = SessionState()
    state.consume_sample_limit_event(_sample_limit_payload())
    assert len(state.items) == 1
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.kind == "sample_limit"
    # 1000.0 tokens → ``1.0k`` via the shared ``_format_token_count``.
    assert chip.header_summary == "limit · token · 1.0k"
    assert chip.body_text == "ran out of tokens"
    assert chip.traceback is None
    assert chip.chip_id.startswith("event-")


def test_consume_sample_limit_event_with_unknown_type_uses_bare_event_word() -> None:
    state = SessionState()
    state.consume_sample_limit_event(
        _sample_limit_payload(limit_type=None, message=None, limit=None)
    )
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "limit"
    assert chip.body_text is None


def test_consume_sample_limit_event_omits_numeric_when_limit_missing() -> None:
    state = SessionState()
    state.consume_sample_limit_event(_sample_limit_payload(limit=None))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "limit · token"
    assert chip.body_text == "ran out of tokens"


def test_consume_sample_limit_event_blank_message_collapses_body_to_none() -> None:
    state = SessionState()
    state.consume_sample_limit_event(_sample_limit_payload(message="   \n   "))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.body_text is None


def test_consume_sample_limit_event_time_limit_renders_with_seconds_suffix() -> None:
    state = SessionState()
    state.consume_sample_limit_event(
        _sample_limit_payload(limit_type="time", limit=60.0, message="time up")
    )
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "limit · time · 60s"


def test_consume_sample_limit_event_cost_limit_renders_with_dollar_prefix() -> None:
    state = SessionState()
    state.consume_sample_limit_event(
        _sample_limit_payload(limit_type="cost", limit=5.5, message="cost cap hit")
    )
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "limit · cost · $5.50"


# ---------------------------------------------------------------------------
# consume_error_event
# ---------------------------------------------------------------------------


def test_consume_error_event_mounts_chip_with_message_and_traceback() -> None:
    """Header stays bare (``error``); message renders on the body row."""
    state = SessionState()
    state.consume_error_event(_error_payload())
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.kind == "error"
    # Bare header — message text is in the body, not inlined here.
    assert chip.header_summary == "error"
    assert chip.body_text == "ValueError: bad input"
    # Plain — exception text isn't authored Markdown, and rendering
    # it through ``StyledMarkdown`` inserted a leading blank row.
    assert chip.body_format == "plain"
    assert chip.traceback is not None
    assert "ValueError" in chip.traceback


def test_consume_error_event_multiline_message_lands_in_body() -> None:
    """Multi-line message renders verbatim in the body — full text preserved."""
    payload = _error_payload(
        message="\n   \nFirst line of error\nSecond line\n", traceback=None
    )
    state = SessionState()
    state.consume_error_event(payload)
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    # Header is just ``error`` — no inlined first-line snippet.
    assert chip.header_summary == "error"
    # Body keeps the full multi-line message.
    assert chip.body_text is not None
    assert "First line of error" in chip.body_text
    assert "Second line" in chip.body_text


def test_consume_error_event_missing_traceback_leaves_field_none() -> None:
    state = SessionState()
    state.consume_error_event(_error_payload(traceback=None))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.traceback is None


def test_consume_error_event_prefers_traceback_ansi_over_plain() -> None:
    """``traceback_ansi`` is preferred over the plain ``traceback`` field.

    It carries the rich-rendered traceback with frame summaries +
    syntax-highlighted source-line context (baked into ANSI escape
    codes by ``format_traceback`` upstream). When both fields are
    present we take the ANSI one so the widget can ``Text.from_ansi``
    it and surface the same styled rendering Inspect's own console
    shows.
    """
    state = SessionState()
    state.consume_error_event(
        _error_payload(
            traceback="plain-traceback-text",
            traceback_ansi="\x1b[31mANSI-traceback-text\x1b[0m",
        )
    )
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.traceback == "\x1b[31mANSI-traceback-text\x1b[0m"


def test_consume_error_event_falls_back_to_plain_traceback_when_ansi_blank() -> None:
    state = SessionState()
    state.consume_error_event(
        _error_payload(traceback="plain-only", traceback_ansi="   ")
    )
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.traceback == "plain-only"


def test_consume_error_event_empty_message_falls_back_to_bare_event_word() -> None:
    state = SessionState()
    state.consume_error_event(_error_payload(message="", traceback=None))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "error"


# ---------------------------------------------------------------------------
# consume_compaction_event
# ---------------------------------------------------------------------------


def test_consume_compaction_event_mounts_chip_with_token_delta() -> None:
    state = SessionState()
    state.consume_compaction_event(_compaction_payload())
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.kind == "compaction"
    assert chip.header_summary == "compaction · summary · tokens 12.3k → 4.1k"
    assert chip.body_text is None


def test_consume_compaction_event_omits_token_clause_when_either_count_missing() -> (
    None
):
    state = SessionState()
    state.consume_compaction_event(
        _compaction_payload(tokens_before=None, tokens_after=None)
    )
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "compaction · summary"


def test_consume_compaction_event_drops_source_body() -> None:
    """Compaction chip is header-only — ``source`` metadata is dropped.

    The header already carries the operationally-important info
    (strategy + token delta); ``source`` is "who ran the compaction"
    metadata that wasn't worth a second row of visual weight.
    """
    state = SessionState()
    state.consume_compaction_event(_compaction_payload(source="auto"))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.body_text is None


# ---------------------------------------------------------------------------
# consume_info_event
# ---------------------------------------------------------------------------


def test_consume_info_event_with_string_data_mounts_text_body() -> None:
    state = SessionState()
    state.consume_info_event(_info_payload(data="subsystem ready"))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.kind == "info"
    assert chip.header_summary == "info · subsystem"
    assert chip.body_text == "subsystem ready"
    # String bodies go through markdown so existing emphasis renders.
    assert chip.body_format == "markdown"


def test_consume_info_event_with_dict_data_emits_raw_json_body() -> None:
    """Structured data → raw JSON text + ``body_format == 'json'``.

    The body is the raw indented JSON text (not markdown-fenced) so
    the widget can pipe it through ``rich.json.JSON`` without the
    markdown code-block background stamping over the chip's tint.
    """
    state = SessionState()
    state.consume_info_event(_info_payload(data={"count": 7, "label": "x"}))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.body_text is not None
    assert chip.body_format == "json"
    # Raw JSON — no markdown fence wrapper.
    assert not chip.body_text.startswith("```")
    assert not chip.body_text.endswith("```")
    assert '"count": 7' in chip.body_text


def test_consume_info_event_with_no_source_falls_back_to_bare_event_word() -> None:
    state = SessionState()
    state.consume_info_event(_info_payload(source=None))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.header_summary == "info"


def test_consume_info_event_with_none_data_collapses_body_to_none() -> None:
    state = SessionState()
    state.consume_info_event(_info_payload(data=None))
    chip = state.items[0]
    assert isinstance(chip, EventChip)
    assert chip.body_text is None


# ---------------------------------------------------------------------------
# consume_inspect_event dispatch + uuid dedup
# ---------------------------------------------------------------------------


def test_consume_inspect_event_routes_sample_limit() -> None:
    state = SessionState()
    state.consume_inspect_event(_wrap_uuid(_sample_limit_payload(), "u-1"))
    assert len(state.items) == 1
    chip = state.items[0]
    assert isinstance(chip, EventChip) and chip.kind == "sample_limit"


def test_consume_inspect_event_routes_error() -> None:
    state = SessionState()
    state.consume_inspect_event(_wrap_uuid(_error_payload(), "u-2"))
    chip = state.items[0]
    assert isinstance(chip, EventChip) and chip.kind == "error"


def test_consume_inspect_event_routes_compaction() -> None:
    state = SessionState()
    state.consume_inspect_event(_wrap_uuid(_compaction_payload(), "u-3"))
    chip = state.items[0]
    assert isinstance(chip, EventChip) and chip.kind == "compaction"


def test_consume_inspect_event_routes_info() -> None:
    state = SessionState()
    state.consume_inspect_event(_wrap_uuid(_info_payload(), "u-4"))
    chip = state.items[0]
    assert isinstance(chip, EventChip) and chip.kind == "info"


def test_consume_inspect_event_dedups_repeat_uuid_across_event_kinds() -> None:
    """Replay on reconnect mustn't double-mount any event-chip family."""
    state = SessionState()
    state.consume_inspect_event(_wrap_uuid(_sample_limit_payload(), "u-dup"))
    state.consume_inspect_event(_wrap_uuid(_sample_limit_payload(), "u-dup"))
    state.consume_inspect_event(_wrap_uuid(_error_payload(), "u-2"))
    state.consume_inspect_event(_wrap_uuid(_error_payload(), "u-2"))
    state.consume_inspect_event(_wrap_uuid(_compaction_payload(), "u-3"))
    state.consume_inspect_event(_wrap_uuid(_compaction_payload(), "u-3"))
    state.consume_inspect_event(_wrap_uuid(_info_payload(), "u-4"))
    state.consume_inspect_event(_wrap_uuid(_info_payload(), "u-4"))
    # Four unique uuids → four chips, not eight.
    assert len(state.items) == 4
    assert all(isinstance(item, EventChip) for item in state.items)


def test_consume_inspect_event_unknown_kind_is_silently_dropped() -> None:
    state = SessionState()
    state.consume_inspect_event({"event": "something_new", "uuid": "u-5"})
    assert state.items == []


# ---------------------------------------------------------------------------
# ScoreChip.answer extraction
# ---------------------------------------------------------------------------


def test_consume_score_event_extracts_answer_when_present() -> None:
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "exact-match",
            "score": {
                "value": "C",
                "answer": "42",
                "explanation": "matches target",
            },
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.answer == "42"


def test_consume_score_event_leaves_answer_none_when_missing() -> None:
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "exact-match",
            "score": {"value": "C", "explanation": "matches"},
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.answer is None


def test_consume_score_event_blank_answer_collapses_to_none() -> None:
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "exact-match",
            "score": {"value": "C", "answer": "   ", "explanation": "ok"},
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.answer is None


# ---------------------------------------------------------------------------
# Helper formatting functions
# ---------------------------------------------------------------------------


def test_format_token_count_below_1k_renders_raw() -> None:
    assert _format_token_count(0) == "0"
    assert _format_token_count(999) == "999"


def test_format_token_count_above_1k_renders_decimal_thousands() -> None:
    assert _format_token_count(1_000) == "1.0k"
    assert _format_token_count(12_345) == "12.3k"
    assert _format_token_count(1_234_567) == "1234.6k"


def test_format_info_data_string_passes_through() -> None:
    assert _format_info_data("hello") == ("hello", "markdown")
    assert _format_info_data("  ") == (None, "markdown")
    assert _format_info_data(None) == (None, "markdown")


def test_format_info_data_dict_emits_raw_json() -> None:
    rendered, fmt = _format_info_data({"a": 1, "b": [2, 3]})
    assert rendered is not None
    assert fmt == "json"
    # No markdown fencing — the widget renders via rich.json.JSON directly so
    # the body inherits the chip's tinted background instead of stamping a
    # dark code-block rectangle over it.
    assert not rendered.startswith("```")
    assert not rendered.endswith("```")
    assert '"a": 1' in rendered


def test_format_info_data_non_jsonable_falls_back_to_repr() -> None:
    """The default=str fallback handles non-JSON-serialisable shapes."""

    class Sentinel:
        def __str__(self) -> str:
            return "sentinel-text"

    rendered, fmt = _format_info_data({"obj": Sentinel()})
    assert rendered is not None
    assert fmt == "json"
    assert "sentinel-text" in rendered


# ---------------------------------------------------------------------------
# chip_id uniqueness + ordering
# ---------------------------------------------------------------------------


def test_event_chip_ids_are_unique_and_ordered() -> None:
    state = SessionState()
    state.consume_sample_limit_event(_sample_limit_payload())
    state.consume_error_event(_error_payload())
    state.consume_compaction_event(_compaction_payload())
    state.consume_info_event(_info_payload())
    ids = [item.chip_id for item in state.items if isinstance(item, EventChip)]
    assert len(set(ids)) == len(ids)
    # Counters increment monotonically.
    assert ids == sorted(ids, key=lambda s: int(s.split("-")[1]))


def test_event_chip_ids_do_not_collide_with_score_chip_ids() -> None:
    state = SessionState()
    state.consume_score_event(
        {"event": "score", "scorer": "s1", "score": {"value": "C"}}
    )
    state.consume_info_event(_info_payload())
    keys = [
        (
            "score"
            if isinstance(item, ScoreChip)
            else "event"
            if isinstance(item, EventChip)
            else "?"
        )
        for item in state.items
    ]
    assert keys == ["score", "event"]
    chip_ids = [
        item.chip_id for item in state.items if isinstance(item, (ScoreChip, EventChip))
    ]
    assert chip_ids[0].startswith("score-")
    assert chip_ids[1].startswith("event-")


# ---------------------------------------------------------------------------
# _classify_score_value (mirrors value_to_float semantics)
# ---------------------------------------------------------------------------


def test_classify_score_value_only_correct_passes() -> None:
    """Only the canonical ``"C"`` sentinel reads as an unambiguous pass.

    ``"P"`` (partial) used to read as passed under the older
    ``>= 0.5`` threshold; under the new 1.0-only rule it's neutral
    so the chip doesn't promote partial credit to a clean win.
    """
    assert _classify_score_value("C") is True
    assert _classify_score_value("I") is None
    assert _classify_score_value("P") is None
    assert _classify_score_value("N") is None


def test_classify_score_value_only_one_classifies_as_passed() -> None:
    """Numeric scalars pass only when exactly ``1.0`` (the upstream cap)."""
    assert _classify_score_value(1.0) is True
    assert _classify_score_value(1) is True
    assert _classify_score_value(0.999) is None
    assert _classify_score_value(0.85) is None
    assert _classify_score_value(0.5) is None
    assert _classify_score_value(0.0) is None
    assert _classify_score_value(0) is None


def test_classify_score_value_booleans() -> None:
    """``True`` maps to 1.0 and passes; ``False`` is neutral (not failed)."""
    assert _classify_score_value(True) is True
    assert _classify_score_value(False) is None


def test_classify_score_value_textual_yes_true_pass() -> None:
    """``yes`` / ``true`` (case-insensitive) pass; their negatives are neutral."""
    assert _classify_score_value("yes") is True
    assert _classify_score_value("YES") is True
    assert _classify_score_value("true") is True
    assert _classify_score_value("True") is True
    assert _classify_score_value("no") is None
    assert _classify_score_value("FALSE") is None


def test_classify_score_value_numeric_strings() -> None:
    """Numeric-string parsing — only ``"1"`` / ``"1.0"`` flag a pass."""
    assert _classify_score_value("1") is True
    assert _classify_score_value("1.0") is True
    assert _classify_score_value("0.85") is None
    assert _classify_score_value("0.3") is None
    assert _classify_score_value("0") is None


def test_classify_score_value_unknown_strings_return_none() -> None:
    """Unrecognised strings collapse to ``None`` — no warning, neutral chip."""
    assert _classify_score_value("rubric: needs more work") is None
    assert _classify_score_value("") is None


def test_classify_score_value_non_scalar_returns_none() -> None:
    """Lists / dicts / ``None`` collapse to ``None`` (no verdict)."""
    assert _classify_score_value([1, 0]) is None
    assert _classify_score_value({"a": 1}) is None
    assert _classify_score_value(None) is None


def test_consume_score_event_classifies_perfect_numeric_value_as_passed() -> None:
    """End-to-end: a ``1.0`` numeric score wires through to ``passed=True``."""
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "model_graded",
            "score": {"value": 1.0, "explanation": "spot on"},
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.passed is True
    assert chip.value == "1.0"


def test_consume_score_event_classifies_partial_value_as_neutral() -> None:
    """A partial-credit numeric score reads as neutral, not failed."""
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "model_graded",
            "score": {"value": 0.85, "explanation": "mostly right"},
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.passed is None
    assert chip.value == "0.85"


def test_consume_score_event_classifies_zero_as_neutral() -> None:
    """A plain ``0`` is neutral too — the chip refuses to claim 'failed'."""
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "exact-match",
            "score": {"value": 0.0, "explanation": "nope"},
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.passed is None


def test_consume_score_event_classifies_non_scalar_as_neutral() -> None:
    """List / dict values give a neutral chip (no pass/fail signal)."""
    state = SessionState()
    state.consume_score_event(
        {
            "event": "score",
            "scorer": "multi",
            "score": {"value": [1, 0, 1]},
        }
    )
    chip = state.items[0]
    assert isinstance(chip, ScoreChip)
    assert chip.passed is None
