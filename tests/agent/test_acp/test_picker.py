"""Phase 9 unit tests for the in-channel session picker module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.schema import AgentMessageChunk, SessionNotification, TextContentBlock

from inspect_ai.agent._acp import _picker
from inspect_ai.agent._acp._picker import (
    PICKER_META_KEY,
    _PickerTarget,
    build_picker_notification,
    list_picker_targets,
    resolve_selection,
)

# ---------------------------------------------------------------------------
# list_picker_targets — filtering and field mapping
# ---------------------------------------------------------------------------


def _make_sample(
    *,
    task: str,
    sample_id: str | int | None,
    epoch: int,
    session_id: str | None,
) -> Any:
    """Build a stub ActiveSample-shaped object for the picker.

    Bare-minimum attributes the picker reads: ``task``, ``sample.id``,
    ``epoch``, ``acp_session`` (with ``.session_id``). Using a plain
    object instead of a real ActiveSample keeps the test independent of
    the ActiveSample constructor's larger field surface.
    """
    sample = MagicMock()
    sample.id = sample_id

    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    if session_id is None:
        active.acp_session = None
    else:
        session = MagicMock()
        session.session_id = session_id
        active.acp_session = session
    return active


def test_list_picker_targets_skips_samples_without_acp_session(monkeypatch) -> None:
    """Samples whose agent never claimed ACP are excluded."""
    samples = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id=None),
        _make_sample(task="t3", sample_id="s3", epoch=0, session_id="uuid-c"),
    ]
    monkeypatch.setattr(_picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == ["uuid-a", "uuid-c"]


def test_list_picker_targets_skips_noop_sessions(monkeypatch) -> None:
    """The noop session sentinel is filtered out."""
    samples = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="noop"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-real"),
    ]
    monkeypatch.setattr(_picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == ["uuid-real"]


def test_list_picker_targets_stringifies_int_sample_id(monkeypatch) -> None:
    """Sample.id may be int; the target's sample_id is always str."""
    samples = [_make_sample(task="t", sample_id=42, epoch=0, session_id="uuid")]
    monkeypatch.setattr(_picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert targets[0].sample_id == "42"


def test_list_picker_targets_handles_none_sample_id(monkeypatch) -> None:
    """Sample.id is Optional; missing ids surface as empty string."""
    samples = [_make_sample(task="t", sample_id=None, epoch=0, session_id="uuid")]
    monkeypatch.setattr(_picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert targets[0].sample_id == ""


def test_list_picker_targets_preserves_order(monkeypatch) -> None:
    """Targets appear in the same order as ``active_samples()``."""
    samples = [
        _make_sample(task=f"t{i}", sample_id=f"s{i}", epoch=0, session_id=f"u{i}")
        for i in range(5)
    ]
    monkeypatch.setattr(_picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == [f"u{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# build_picker_notification — payload shape + structured _meta
# ---------------------------------------------------------------------------


def _targets(*spec: tuple[str, str, str, int]) -> list[_PickerTarget]:
    """Compact target-list constructor: (session_id, task, sample_id, epoch)."""
    return [_PickerTarget(*t) for t in spec]


def test_build_picker_notification_session_id_matches_control() -> None:
    """The notification's session_id is the control session, not a target."""
    targets = _targets(("uuid-1", "t", "s", 0))
    notif = build_picker_notification("control-uuid", targets)
    assert notif.session_id == "control-uuid"


def test_build_picker_notification_body_is_agent_message_chunk() -> None:
    """Visible body is an agent_message_chunk with a text block."""
    targets = _targets(("uuid-1", "task-a", "sample-1", 0))
    notif = build_picker_notification("control", targets)
    assert isinstance(notif.update, AgentMessageChunk)
    assert isinstance(notif.update.content, TextContentBlock)


def test_build_picker_notification_text_lists_all_targets() -> None:
    """Text body lists each target with its index, task, sample, epoch, uuid."""
    targets = _targets(
        ("uuid-a", "task-a", "sample-1", 0),
        ("uuid-b", "task-b", "sample-2", 1),
    )
    notif = build_picker_notification("control", targets)
    assert isinstance(notif.update, AgentMessageChunk)
    assert isinstance(notif.update.content, TextContentBlock)
    text = notif.update.content.text

    assert "1." in text and "2." in text
    assert "task-a" in text and "task-b" in text
    assert "sample-1" in text and "sample-2" in text
    assert "epoch 0" in text and "epoch 1" in text
    assert "uuid-a" in text and "uuid-b" in text


def test_build_picker_notification_carries_structured_meta() -> None:
    """`_meta[PICKER_META_KEY]` holds the structured target list."""
    targets = _targets(
        ("uuid-a", "task-a", "sample-1", 0),
        ("uuid-b", "task-b", "sample-2", 3),
    )
    notif = build_picker_notification("control", targets)
    assert notif.field_meta is not None
    assert PICKER_META_KEY in notif.field_meta
    entries = notif.field_meta[PICKER_META_KEY]
    assert entries == [
        {"sessionId": "uuid-a", "task": "task-a", "sampleId": "sample-1", "epoch": 0},
        {"sessionId": "uuid-b", "task": "task-b", "sampleId": "sample-2", "epoch": 3},
    ]


def test_build_picker_notification_empty_targets_shows_helpful_text() -> None:
    """With zero targets the text explains the situation rather than being blank."""
    notif = build_picker_notification("control", [])
    assert isinstance(notif.update, AgentMessageChunk)
    assert isinstance(notif.update.content, TextContentBlock)
    text = notif.update.content.text
    assert "No sessions" in text
    # Structured _meta is still present (with an empty list), so a
    # capability-aware client doesn't have to special-case missing data.
    assert notif.field_meta is not None
    assert notif.field_meta[PICKER_META_KEY] == []


def test_build_picker_notification_meta_preserves_order() -> None:
    """Structured _meta entries appear in the same order as the visible text."""
    targets = _targets(
        ("uuid-z", "zz", "1", 0),
        ("uuid-a", "aa", "2", 0),
        ("uuid-m", "mm", "3", 0),
    )
    notif = build_picker_notification("control", targets)
    assert notif.field_meta is not None
    ids = [e["sessionId"] for e in notif.field_meta[PICKER_META_KEY]]
    assert ids == ["uuid-z", "uuid-a", "uuid-m"]


# ---------------------------------------------------------------------------
# resolve_selection — numeric index, uuid match, error cases
# ---------------------------------------------------------------------------


def test_resolve_selection_by_numeric_index() -> None:
    """A 1-based numeric string picks the matching target."""
    targets = _targets(
        ("uuid-a", "t", "1", 0),
        ("uuid-b", "t", "2", 0),
        ("uuid-c", "t", "3", 0),
    )
    assert resolve_selection("1", targets).session_id == "uuid-a"  # type: ignore[union-attr]
    assert resolve_selection("2", targets).session_id == "uuid-b"  # type: ignore[union-attr]
    assert resolve_selection("3", targets).session_id == "uuid-c"  # type: ignore[union-attr]


def test_resolve_selection_by_session_id() -> None:
    """A uuid match returns the matching target regardless of order."""
    targets = _targets(
        ("uuid-a", "t", "1", 0),
        ("uuid-b", "t", "2", 0),
    )
    assert resolve_selection("uuid-b", targets).session_id == "uuid-b"  # type: ignore[union-attr]


def test_resolve_selection_index_out_of_range_returns_none() -> None:
    """Index '0' (invalid; we're 1-based) and indexes past the end return None."""
    targets = _targets(("uuid-a", "t", "1", 0), ("uuid-b", "t", "2", 0))
    assert resolve_selection("0", targets) is None
    assert resolve_selection("3", targets) is None
    assert resolve_selection("99", targets) is None


def test_resolve_selection_negative_index_returns_none() -> None:
    """Negative indexes are rejected (parse as int, fail the 1<=i<=N check)."""
    targets = _targets(("uuid-a", "t", "1", 0))
    assert resolve_selection("-1", targets) is None


def test_resolve_selection_unknown_uuid_returns_none() -> None:
    """A uuid string that doesn't match any target returns None."""
    targets = _targets(("uuid-a", "t", "1", 0))
    assert resolve_selection("uuid-nope", targets) is None


def test_resolve_selection_empty_string_returns_none() -> None:
    """Empty or whitespace-only selection returns None."""
    targets = _targets(("uuid-a", "t", "1", 0))
    assert resolve_selection("", targets) is None
    assert resolve_selection("   ", targets) is None


def test_resolve_selection_strips_whitespace() -> None:
    """Leading/trailing whitespace is tolerated on both index and uuid input."""
    targets = _targets(("uuid-a", "t", "1", 0), ("uuid-b", "t", "2", 0))
    assert resolve_selection("  1  ", targets).session_id == "uuid-a"  # type: ignore[union-attr]
    assert resolve_selection("\tuuid-b\n", targets).session_id == "uuid-b"  # type: ignore[union-attr]


def test_resolve_selection_against_empty_target_list_returns_none() -> None:
    """With no targets, every selection is invalid."""
    assert resolve_selection("1", []) is None
    assert resolve_selection("anything", []) is None


@pytest.mark.parametrize("garbage", ["abc", "1.5", "1,2", "a1", "1abc"])
def test_resolve_selection_malformed_input_returns_none(garbage: str) -> None:
    """Strings that aren't ints AND don't match any uuid return None."""
    targets = _targets(("uuid-a", "t", "1", 0))
    assert resolve_selection(garbage, targets) is None


# ---------------------------------------------------------------------------
# Notification roundtrips through Pydantic serialization
# ---------------------------------------------------------------------------


def test_notification_serializes_meta_under_underscore_meta_alias() -> None:
    """When the notification is dumped to JSON the `_meta` alias is used.

    ACP's `_meta` field is exposed in Python as `field_meta` but the
    wire-format alias is `_meta`. Verify a round-trip preserves that
    alias so clients see the standard ACP key.
    """
    targets = _targets(("uuid-a", "t", "s", 0))
    notif = build_picker_notification("ctrl", targets)
    dumped = notif.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "_meta" in dumped
    assert PICKER_META_KEY in dumped["_meta"]

    # Round-trip back through validation; meta survives.
    reloaded = SessionNotification.model_validate(dumped)
    assert reloaded.field_meta is not None
    assert reloaded.field_meta[PICKER_META_KEY] == [
        {"sessionId": "uuid-a", "task": "t", "sampleId": "s", "epoch": 0},
    ]
