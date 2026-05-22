"""Phase 9 unit tests for the in-channel session picker module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.schema import AgentMessageChunk, SessionNotification, TextContentBlock

from inspect_ai.agent._acp import picker
from inspect_ai.agent._acp.inspect_ext import (
    PICKER_META_KEY,
    build_picker_notification,
    sample_listing_meta_dict,
)
from inspect_ai.agent._acp.picker import (
    PickerTarget,
    SampleListing,
    list_all_samples,
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
    agent_name: str | None = None,
    started: float | None = None,
    fails_on_error: bool = True,
) -> Any:
    """Build a stub ActiveSample-shaped object for the picker.

    Bare-minimum attributes the picker reads: ``task``, ``sample.id``,
    ``epoch``, ``acp_session`` (with ``.session_id``), ``agent_name``,
    ``started``, ``fails_on_error`` (collapsed bool). Using a plain
    object instead of a real ActiveSample keeps the test independent
    of the ActiveSample constructor's larger field surface.

    Default ``fails_on_error=True`` mirrors what the eval harness
    produces from the default ``EvalConfig.fail_on_error=None``
    (which collapses to True in ``ActiveSample.fails_on_error``).
    """
    sample = MagicMock()
    sample.id = sample_id

    active = MagicMock()
    active.task = task
    active.sample = sample
    active.epoch = epoch
    active.agent_name = agent_name
    active.started = started
    active.fails_on_error = fails_on_error
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
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == ["uuid-a", "uuid-c"]


def test_list_picker_targets_skips_noop_sessions(monkeypatch) -> None:
    """The noop session sentinel is filtered out."""
    samples = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="noop"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-real"),
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == ["uuid-real"]


def test_list_picker_targets_stringifies_int_sample_id(monkeypatch) -> None:
    """Sample.id may be int; the target's sample_id is always str."""
    samples = [_make_sample(task="t", sample_id=42, epoch=0, session_id="uuid")]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert targets[0].sample_id == "42"


def test_list_picker_targets_handles_none_sample_id(monkeypatch) -> None:
    """Sample.id is Optional; missing ids surface as empty string."""
    samples = [_make_sample(task="t", sample_id=None, epoch=0, session_id="uuid")]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert targets[0].sample_id == ""


def test_list_picker_targets_preserves_order(monkeypatch) -> None:
    """Targets appear in the same order as ``active_samples()``."""
    samples = [
        _make_sample(task=f"t{i}", sample_id=f"s{i}", epoch=0, session_id=f"u{i}")
        for i in range(5)
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == [f"u{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# build_picker_notification — payload shape + structured _meta
# ---------------------------------------------------------------------------


def _targets(*spec: tuple[str, str, str, int]) -> list[PickerTarget]:
    """Compact target-list constructor: (session_id, task, sample_id, epoch)."""
    return [PickerTarget(*t) for t in spec]


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
        {
            "sessionId": "uuid-a",
            "task": "task-a",
            "sampleId": "sample-1",
            "epoch": 0,
            "agentName": None,
            "startedAt": None,
            "totalMessages": 0,
            "totalTokens": 0,
            "failsOnError": False,
        },
        {
            "sessionId": "uuid-b",
            "task": "task-b",
            "sampleId": "sample-2",
            "epoch": 3,
            "agentName": None,
            "startedAt": None,
            "totalMessages": 0,
            "totalTokens": 0,
            "failsOnError": False,
        },
    ]


def test_build_picker_notification_meta_includes_agent_and_started_at() -> None:
    """The extension #1 / #5 fields propagate from PickerTarget into _meta."""
    targets = [
        PickerTarget(
            session_id="uuid-x",
            task="t",
            sample_id="s",
            epoch=0,
            agent_name="react",
            started_at=1_700_000_000.5,
        )
    ]
    notif = build_picker_notification("control", targets)
    assert notif.field_meta is not None
    entry = notif.field_meta[PICKER_META_KEY][0]
    assert entry["agentName"] == "react"
    assert entry["startedAt"] == 1_700_000_000.5


def test_list_picker_targets_propagates_agent_name_and_started(monkeypatch) -> None:
    """``ActiveSample.agent_name`` and ``ActiveSample.started`` reach the target."""
    samples = [
        _make_sample(
            task="t",
            sample_id="s",
            epoch=0,
            session_id="uuid",
            agent_name="react",
            started=1_700_000_000.0,
        )
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert targets[0].agent_name == "react"
    assert targets[0].started_at == 1_700_000_000.0


def test_picker_fails_on_error_mirrors_active_sample(monkeypatch) -> None:
    """``PickerTarget.fails_on_error`` mirrors ``ActiveSample.fails_on_error``.

    The picker reads the already-collapsed boolean rather than the
    raw config value so the ACP TUI's ``[e] error`` visibility lines
    up exactly with the in-proc ``--display full`` rule
    (``cancel_with_error.display = not sample.fails_on_error``).
    Fractional / integer-count configs that collapse to ``True`` in
    ``ActiveSample.fails_on_error`` will hide ``[e] error`` here too.
    """
    samples = [
        _make_sample(
            task="t",
            sample_id="s1",
            epoch=0,
            session_id="u1",
            fails_on_error=True,
        ),
        _make_sample(
            task="t",
            sample_id="s2",
            epoch=0,
            session_id="u2",
            fails_on_error=False,
        ),
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    targets = list_picker_targets()
    assert [t.session_id for t in targets] == ["u1", "u2"]
    assert targets[0].fails_on_error is True  # hide [e] error
    assert targets[1].fails_on_error is False  # show [e] error


def test_build_picker_notification_meta_includes_fails_on_error() -> None:
    """``failsOnError`` rides in the structured ``_meta`` payload.

    Drives delivery to the TUI on both attach paths: direct-attach via
    ``session/load`` reads it from the binding-confirmation; picker-
    attach reads it from the parallel ``inspect/list_sessions``
    response (built from the same ``picker_target_meta_dict``).
    """
    targets = [
        PickerTarget(
            session_id="uuid-x",
            task="t",
            sample_id="s",
            epoch=0,
            fails_on_error=True,
        )
    ]
    notif = build_picker_notification("control", targets)
    assert notif.field_meta is not None
    entry = notif.field_meta[PICKER_META_KEY][0]
    assert entry["failsOnError"] is True


def test_list_picker_targets_propagates_total_tokens(monkeypatch) -> None:
    """``ActiveSample.total_tokens`` mutations are visible to the picker.

    Pins that reading the attribute is live: the picker captures the
    current value at each enumeration call, so token totals advancing
    server-side reach the TUI on the next rescan tick.
    """
    sample = _make_sample(
        task="t",
        sample_id="s",
        epoch=0,
        session_id="uuid",
    )
    sample.total_tokens = 0
    monkeypatch.setattr(picker, "active_samples", lambda: [sample])

    assert list_picker_targets()[0].total_tokens == 0

    # Simulate the agent racking up tokens between rescans.
    sample.total_tokens = 12_345
    assert list_picker_targets()[0].total_tokens == 12_345


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


# ---------------------------------------------------------------------------
# list_all_samples — superset enumeration for the Inspect TUI
# ---------------------------------------------------------------------------


def test_list_all_samples_includes_non_acp_samples(monkeypatch) -> None:
    """ACP-claimed AND non-claimed samples both appear; sessionId reflects status."""
    samples = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="uuid-a"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id=None),
        _make_sample(task="t3", sample_id="s3", epoch=0, session_id="uuid-c"),
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    listings = list_all_samples()
    assert [(listing.sample_id, listing.session_id) for listing in listings] == [
        ("s1", "uuid-a"),
        ("s2", None),
        ("s3", "uuid-c"),
    ]


def test_list_all_samples_treats_noop_session_as_non_acp(monkeypatch) -> None:
    """The ``noop`` sentinel surfaces as ``session_id=None`` (pre-claim placeholder)."""
    samples = [
        _make_sample(task="t1", sample_id="s1", epoch=0, session_id="noop"),
        _make_sample(task="t2", sample_id="s2", epoch=0, session_id="uuid-real"),
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    listings = list_all_samples()
    assert listings[0].session_id is None
    assert listings[1].session_id == "uuid-real"


def test_list_all_samples_stringifies_sample_id(monkeypatch) -> None:
    """Sample.id may be int or None — mirror ``list_picker_targets`` exactly."""
    samples = [
        _make_sample(task="t", sample_id=42, epoch=0, session_id="uuid"),
        _make_sample(task="t", sample_id=None, epoch=0, session_id=None),
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    listings = list_all_samples()
    assert listings[0].sample_id == "42"
    assert listings[1].sample_id == ""


def test_list_all_samples_propagates_fields(monkeypatch) -> None:
    """Field mapping mirrors ``list_picker_targets`` for the shared fields."""
    sample = _make_sample(
        task="t",
        sample_id="s",
        epoch=2,
        session_id="uuid-x",
        agent_name="react",
        started=1_700_000_000.0,
        fails_on_error=True,
    )
    sample.total_tokens = 99_999
    monkeypatch.setattr(picker, "active_samples", lambda: [sample])

    listing = list_all_samples()[0]
    assert listing.task == "t"
    assert listing.epoch == 2
    assert listing.session_id == "uuid-x"
    assert listing.agent_name == "react"
    assert listing.started_at == 1_700_000_000.0
    assert listing.fails_on_error is True
    assert listing.total_tokens == 99_999


def test_list_all_samples_strips_agent_name_for_non_acp(monkeypatch) -> None:
    """Non-ACP samples surface as ``agent_name=None`` regardless of the solver name.

    The column header reads ``acp agent``; surfacing a solver name on
    a non-ACP row would be misleading (there's no attachable ACP
    agent behind that name). Keeps the wire payload consistent with
    the TUI's display, which always shows ``—`` for non-ACP rows.
    """
    samples = [
        # Non-ACP sample with a solver name — name must be stripped.
        _make_sample(
            task="t1",
            sample_id="s1",
            epoch=0,
            session_id=None,
            agent_name="some_solver",
        ),
        # Noop sentinel counts as non-ACP — also stripped.
        _make_sample(
            task="t2",
            sample_id="s2",
            epoch=0,
            session_id="noop",
            agent_name="react",
        ),
        # ACP-claimed sample keeps its name.
        _make_sample(
            task="t3",
            sample_id="s3",
            epoch=0,
            session_id="uuid-real",
            agent_name="react",
        ),
    ]
    monkeypatch.setattr(picker, "active_samples", lambda: samples)

    listings = list_all_samples()
    assert [(listing.session_id, listing.agent_name) for listing in listings] == [
        (None, None),
        (None, None),
        ("uuid-real", "react"),
    ]


# ---------------------------------------------------------------------------
# sample_listing_meta_dict — wire shape
# ---------------------------------------------------------------------------


def test_sample_listing_meta_dict_emits_camelcase_with_session_id() -> None:
    """ACP-claimed listing carries ``sessionId`` (uuid)."""
    listing = SampleListing(
        session_id="uuid-x",
        task="t",
        sample_id="s",
        epoch=0,
        agent_name="react",
        started_at=1_700_000_000.0,
        total_messages=42,
        total_tokens=12_345,
        fails_on_error=True,
    )
    assert sample_listing_meta_dict(listing) == {
        "sessionId": "uuid-x",
        "task": "t",
        "sampleId": "s",
        "epoch": 0,
        "agentName": "react",
        "startedAt": 1_700_000_000.0,
        "totalMessages": 42,
        "totalTokens": 12_345,
        "failsOnError": True,
    }


def test_sample_listing_meta_dict_session_id_null_for_non_acp() -> None:
    """Non-claimed listing emits ``sessionId: None`` — the discriminator the TUI keys on."""
    listing = SampleListing(
        session_id=None,
        task="t",
        sample_id="s",
        epoch=0,
    )
    payload = sample_listing_meta_dict(listing)
    assert payload["sessionId"] is None
    # Other fields still present with defaults — keeps the wire shape stable.
    assert payload["agentName"] is None
    assert payload["startedAt"] is None
    assert payload["totalMessages"] == 0
    assert payload["totalTokens"] == 0
    assert payload["failsOnError"] is False


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
        {
            "sessionId": "uuid-a",
            "task": "t",
            "sampleId": "s",
            "epoch": 0,
            "agentName": None,
            "startedAt": None,
            "totalMessages": 0,
            "totalTokens": 0,
            "failsOnError": False,
        },
    ]
