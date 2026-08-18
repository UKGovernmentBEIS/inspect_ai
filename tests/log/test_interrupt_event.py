"""Phase 2 unit tests for `InterruptEvent` and `ChatMessageUser.source="operator"`."""

import pytest
from pydantic import TypeAdapter, ValidationError

from inspect_ai.event import Event, InterruptEvent
from inspect_ai.log._transcript import (
    Transcript,
    _transcript,
    record_interrupt_event,
)
from inspect_ai.model import ChatMessageUser


def test_interrupt_event_required_fields() -> None:
    event = InterruptEvent(source="user_cancel", interrupted="generate")
    assert event.event == "interrupt"
    assert event.source == "user_cancel"
    assert event.interrupted == "generate"
    assert event.interrupted_tool_call_id is None
    assert event.interrupted_model_event_id is None


def test_interrupt_event_with_optional_ids() -> None:
    event = InterruptEvent(
        source="user_cancel",
        interrupted="tool_call",
        interrupted_tool_call_id="tool-xyz",
        interrupted_model_event_id="event-abc",
    )
    assert event.interrupted_tool_call_id == "tool-xyz"
    assert event.interrupted_model_event_id == "event-abc"


def test_interrupt_event_inherits_base_event_fields() -> None:
    event = InterruptEvent(source="limit", interrupted="between_turns")
    assert event.uuid is not None
    assert event.timestamp is not None


def test_interrupt_event_source_validation() -> None:
    with pytest.raises(ValidationError):
        InterruptEvent(source="bogus", interrupted="generate")  # type: ignore[arg-type]


def test_interrupt_event_interrupted_validation() -> None:
    with pytest.raises(ValidationError):
        InterruptEvent(source="user_cancel", interrupted="bogus")  # type: ignore[arg-type]


def test_interrupt_event_roundtrip_via_event_union() -> None:
    original = InterruptEvent(
        source="system",
        interrupted="tool_call",
        interrupted_tool_call_id="tc-1",
    )
    dumped = original.model_dump()
    restored: Event = TypeAdapter(Event).validate_python(dumped)
    assert isinstance(restored, InterruptEvent)
    assert restored.source == "system"
    assert restored.interrupted == "tool_call"
    assert restored.interrupted_tool_call_id == "tc-1"
    assert restored.interrupted_model_event_id is None
    assert restored.uuid == original.uuid


def test_record_interrupt_event_appends_to_current_transcript() -> None:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        record_interrupt_event(
            source="user_cancel",
            interrupted="generate",
            interrupted_model_event_id="me-1",
        )
    finally:
        _transcript.reset(token)

    assert len(transcript.events) == 1
    event = transcript.events[0]
    assert isinstance(event, InterruptEvent)
    assert event.source == "user_cancel"
    assert event.interrupted == "generate"
    assert event.interrupted_model_event_id == "me-1"
    assert event.interrupted_tool_call_id is None


def test_chat_message_user_accepts_operator_source() -> None:
    message = ChatMessageUser(content="hi", source="operator")
    assert message.source == "operator"


def test_chat_message_user_accepts_all_three_sources() -> None:
    for src in ("input", "generate", "operator"):
        message = ChatMessageUser(content="hi", source=src)
        assert message.source == src


def test_chat_message_user_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        ChatMessageUser(content="hi", source="bogus")  # type: ignore[arg-type]


def test_chat_message_user_operator_source_roundtrips() -> None:
    original = ChatMessageUser(content="hello", source="operator")
    dumped = original.model_dump()
    restored = ChatMessageUser.model_validate(dumped)
    assert restored.source == "operator"
    assert restored.content == "hello"


def test_partition_messages_treats_operator_as_conversation() -> None:
    """Operator messages are runtime injections, not original sample input.

    They flow into the conversation partition (so compaction may
    summarize them) — only ``source == "input"`` is preserved as input.
    """
    from inspect_ai.model._chat_message import ChatMessage
    from inspect_ai.model._trim import partition_messages

    msgs: list[ChatMessage] = [
        ChatMessageUser(content="seed", source="input"),
        ChatMessageUser(content="midstream", source="operator"),
    ]
    partitioned = partition_messages(msgs)
    assert any(m.source == "input" for m in partitioned.input)
    assert any(m.source == "operator" for m in partitioned.conversation)
    assert not any(m.source == "operator" for m in partitioned.input)
