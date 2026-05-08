"""Tests for event-assertion helpers."""

# pyright: reportImplicitRelativeImport=false

from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest

from _helpers.event_assertions import (
    assert_attempt_group,
    assert_call_field_invariants,
    assert_no_legacy_rewrite,
)
from inspect_ai.event._model import ModelEvent
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


def _ev(
    *,
    call_id: str | None,
    attempt: int | None,
    ts_offset_seconds: float = 0,
    working_start: float = 0.0,
    working_time: float = 0.5,
    error: str | None = None,
    cache: Literal["read", "write"] | None = None,
    call_started_at: datetime | None = None,
    call_completed_at: datetime | None = None,
    call_working_start: float | None = None,
    call_working_time: float | None = None,
    call_retries: int | None = None,
    http_retries: int | None = None,
) -> ModelEvent:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return ModelEvent(
        model="fake",
        input=[ChatMessageUser(content="x")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("fake", "ok"),
        call_id=call_id,
        attempt=attempt,
        timestamp=base + timedelta(seconds=ts_offset_seconds),
        working_start=working_start,
        working_time=working_time,
        completed=base + timedelta(seconds=ts_offset_seconds + working_time),
        error=error,
        cache=cache,
        call_started_at=call_started_at,
        call_completed_at=call_completed_at,
        call_working_start=call_working_start,
        call_working_time=call_working_time,
        call_retries=call_retries,
        http_retries=http_retries,
    )


def test_assert_attempt_group_passes_for_success_sequence() -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev(call_id="abc", attempt=1, ts_offset_seconds=0, error="boom"),
        _ev(call_id="abc", attempt=2, ts_offset_seconds=1, error="boom"),
        _ev(
            call_id="abc",
            attempt=3,
            ts_offset_seconds=2,
            call_started_at=base,
            call_completed_at=base + timedelta(seconds=2.5),
            call_working_start=0.0,
            call_working_time=1.5,
            call_retries=2,
            http_retries=2,
        ),
    ]
    assert_attempt_group(events, retries=2, terminal_kind="success")


def test_assert_no_legacy_rewrite_flags_inversion() -> None:
    events = [
        _ev(call_id="abc", attempt=1, ts_offset_seconds=10, error="boom"),
        _ev(call_id="abc", attempt=2, ts_offset_seconds=0),
    ]
    with pytest.raises(AssertionError, match="timestamp inversion"):
        assert_no_legacy_rewrite(events)


def test_assert_call_field_invariants_terminal_success() -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _ev(
        call_id="x",
        attempt=1,
        call_started_at=base,
        call_completed_at=base + timedelta(seconds=1),
        call_working_start=0.0,
        call_working_time=0.5,
        call_retries=0,
        http_retries=0,
    )
    assert_call_field_invariants(ev, kind="terminal-success")


def test_assert_call_field_invariants_non_terminal_no_call_fields() -> None:
    ev = _ev(call_id="x", attempt=1, error="boom")
    assert_call_field_invariants(ev, kind="non-terminal")
