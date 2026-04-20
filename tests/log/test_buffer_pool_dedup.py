import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


@pytest.fixture
def db() -> Generator[SampleBufferDatabase, None, None]:
    with tempfile.TemporaryDirectory() as db_dir:
        test_db = SampleBufferDatabase(location="test_location", db_dir=Path(db_dir))
        yield test_db
        test_db.cleanup()


def _make_model_event(
    input_msgs: list,
    *,
    call_messages: list | None = None,
) -> ModelEvent:
    event = ModelEvent(
        model="test-model",
        input=input_msgs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
    )
    if call_messages is not None:
        event = event.model_copy(
            update={
                "call": ModelCall(
                    request={"model": "test", "messages": call_messages},
                    response={"id": "r1", "choices": []},
                )
            }
        )
    return event


def test_buffer_pool_dedup_reduces_event_size(db: SampleBufferDatabase) -> None:
    """Recording N turns through the buffer DB produces pool entries, not copies."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_a = ChatMessageUser(content="Hello")
    msg_b = ChatMessageAssistant(content="Hi there")
    msg_c = ChatMessageUser(content="How are you?")

    # Turn 1: [msg_a]
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a]))])
    # Turn 2: [msg_a, msg_b]
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b]))]
    )
    # Turn 3: [msg_a, msg_b, msg_c]
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b, msg_c]))]
    )

    # Read back via get_sample_data
    data = db.get_sample_data("s1", 1)
    assert data is not None

    # Should have 3 message pool entries (a, b, c)
    assert len(data.message_pool) == 3

    # Events should have input_refs, not full input lists
    for ev in data.events:
        event_dict = ev.event
        assert isinstance(event_dict, dict)
        assert event_dict.get("input_refs") is not None, "Event should have input_refs"
        assert event_dict.get("input") == [], "Event input should be empty (condensed)"

    # Verify pool data can be deserialized
    pool_msgs = [json.loads(entry.data) for entry in data.message_pool]
    assert pool_msgs[0]["content"] == "Hello"
    assert pool_msgs[1]["content"] == "Hi there"
    assert pool_msgs[2]["content"] == "How are you?"


def test_buffer_pool_incremental_delivery(db: SampleBufferDatabase) -> None:
    """Pool entries are delivered incrementally via after_message_pool_id."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_a = ChatMessageUser(content="Hello")
    msg_b = ChatMessageAssistant(content="Hi")
    msg_c = ChatMessageUser(content="Bye")

    # Log first two turns
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a]))])
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b]))]
    )

    # First fetch: no cursor -> all pool entries
    data1 = db.get_sample_data("s1", 1)
    assert data1 is not None
    assert len(data1.message_pool) == 2

    # Record the high-water mark
    last_pool_id = max(entry.id for entry in data1.message_pool)

    # Log third turn
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b, msg_c]))]
    )

    # Second fetch: with cursor -> only the new entry
    data2 = db.get_sample_data("s1", 1, after_message_pool_id=last_pool_id)
    assert data2 is not None
    assert len(data2.message_pool) == 1
    assert json.loads(data2.message_pool[0].data)["content"] == "Bye"


def test_buffer_call_pool_dedup(db: SampleBufferDatabase) -> None:
    """Call pool entries are deduped across multiple turns and events have call_refs."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    call_msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]

    # Turn 1: two call messages
    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_model_event(
                    [ChatMessageUser(content="Hello")],
                    call_messages=call_msgs,
                ),
            )
        ]
    )

    # Turn 2: same call messages plus a new one (dedup should apply)
    call_msgs_2 = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Follow-up"},
    ]
    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_model_event(
                    [ChatMessageUser(content="Hello")],
                    call_messages=call_msgs_2,
                ),
            )
        ]
    )

    data = db.get_sample_data("s1", 1)
    assert data is not None

    # 5 total call message references across 2 events, but only 3 unique in pool
    assert len(data.call_pool) == 3

    # Both events should have call_refs
    for ev in data.events:
        event_dict = ev.event
        assert isinstance(event_dict, dict)
        call_dict = event_dict.get("call", {})
        assert isinstance(call_dict, dict)
        assert call_dict.get("call_refs") is not None


def test_buffer_call_pool_incremental_delivery(db: SampleBufferDatabase) -> None:
    """Call pool entries are delivered incrementally via after_call_pool_id."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    call_msgs_1 = [{"role": "user", "content": "Hello"}]
    call_msgs_2 = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]

    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_model_event(
                    [ChatMessageUser(content="Hello")],
                    call_messages=call_msgs_1,
                ),
            )
        ]
    )

    # First fetch: no cursor -> all pool entries
    data1 = db.get_sample_data("s1", 1)
    assert data1 is not None
    assert len(data1.call_pool) == 1

    last_call_pool_id = max(entry.id for entry in data1.call_pool)

    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_model_event(
                    [ChatMessageUser(content="Hello")],
                    call_messages=call_msgs_2,
                ),
            )
        ]
    )

    # Second fetch: with cursor -> only the new entry
    data2 = db.get_sample_data("s1", 1, after_call_pool_id=last_call_pool_id)
    assert data2 is not None
    assert len(data2.call_pool) == 1
    assert json.loads(data2.call_pool[0].data)["content"] == "Hi"


def test_buffer_pool_cleanup_on_remove(db: SampleBufferDatabase) -> None:
    """Pool data is no longer returned after a sample is removed."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    db.log_events(
        [
            SampleEvent(
                id="s1",
                epoch=1,
                event=_make_model_event(
                    [ChatMessageUser(content="Hello")],
                    call_messages=[{"role": "user", "content": "Hello"}],
                ),
            )
        ]
    )

    # Verify pools exist before removal
    data = db.get_sample_data("s1", 1)
    assert data is not None
    assert len(data.message_pool) == 1
    assert len(data.call_pool) == 1

    # Remove sample
    db.remove_samples([("s1", 1)])

    # Verify pool data is no longer returned
    data_after = db.get_sample_data("s1", 1)
    assert data_after is None or (
        len(data_after.message_pool) == 0 and len(data_after.call_pool) == 0
    )


def test_buffer_pool_refs_resolve_correctly(db: SampleBufferDatabase) -> None:
    """input_refs resolve to the correct messages across multiple turns."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_a = ChatMessageUser(content="Hello")
    msg_b = ChatMessageAssistant(content="Hi there")
    msg_c = ChatMessageUser(content="How are you?")

    # Turn 1: [A]
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a]))])
    # Turn 2: [A, B]
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b]))]
    )
    # Turn 3: [A, B, C]
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_a, msg_b, msg_c]))]
    )

    data = db.get_sample_data("s1", 1)
    assert data is not None

    # Deserialize the pool into a list of ChatMessage objects
    pool = [json.loads(entry.data) for entry in data.message_pool]

    # Resolve each event's input_refs and verify correct messages
    expected_contents = [
        ["Hello"],
        ["Hello", "Hi there"],
        ["Hello", "Hi there", "How are you?"],
    ]
    for i, ev in enumerate(data.events):
        event_dict = ev.event
        assert isinstance(event_dict, dict)
        input_refs = event_dict.get("input_refs")
        assert isinstance(input_refs, list), f"Event {i} missing input_refs"

        # Expand refs against pool
        resolved = []
        for ref in input_refs:
            assert isinstance(ref, list) and len(ref) == 2
            assert isinstance(ref[0], int) and isinstance(ref[1], int)
            resolved.extend(pool[ref[0] : ref[1]])

        actual_contents = [msg["content"] for msg in resolved]
        assert actual_contents == expected_contents[i], (
            f"Event {i}: expected {expected_contents[i]}, got {actual_contents}"
        )


def test_buffer_pool_dedup_uses_content_hash_not_msg_id(
    db: SampleBufferDatabase,
) -> None:
    """Messages with same content but different .id fields dedup to one pool entry."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    # Two distinct ChatMessage objects with identical content but different .id
    msg_1 = ChatMessageUser(content="Hello").model_copy(update={"id": "uuid-aaa"})
    msg_2 = ChatMessageUser(content="Hello").model_copy(update={"id": "uuid-bbb"})

    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_1]))])
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_2]))])

    data = db.get_sample_data("s1", 1)
    assert data is not None

    # Same content -> should be 1 pool entry, not 2
    assert len(data.message_pool) == 1, (
        f"Expected 1 pool entry for identical content, got {len(data.message_pool)}"
    )
