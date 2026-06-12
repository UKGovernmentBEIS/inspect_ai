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


def test_buffer_pool_late_model_event_after_complete_raises(
    db: SampleBufferDatabase,
) -> None:
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)
    db.complete_sample(sample)

    with pytest.raises(RuntimeError, match="after complete_sample"):
        db.log_events(
            [
                SampleEvent(
                    id="s1",
                    epoch=1,
                    event=_make_model_event([ChatMessageUser(content="late")]),
                )
            ]
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
    # Turn 3: [C, A, B] verifies refs resolve by pool index.
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_c, msg_a, msg_b]))]
    )

    data = db.get_sample_data("s1", 1)
    assert data is not None

    # Deserialize the pool into a list of ChatMessage objects
    pool = [json.loads(entry.data) for entry in data.message_pool]

    # Resolve each event's input_refs and verify correct messages
    expected_contents = [
        ["Hello"],
        ["Hello", "Hi there"],
        ["How are you?", "Hello", "Hi there"],
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


# ---------------------------------------------------------------------------
# Pool-index dedup semantics
# ---------------------------------------------------------------------------


def _start_sample(db: SampleBufferDatabase) -> None:
    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="test", target="target"))


def _log_model_event(db: SampleBufferDatabase, input_msgs: list) -> None:
    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event(input_msgs))])


def _pool_contents(db: SampleBufferDatabase) -> list[str]:
    data = db.get_sample_data("s1", 1)
    assert data is not None
    return [json.loads(entry.data)["content"] for entry in data.message_pool]


def test_clone_then_mutate_gets_own_pool_entry(db: SampleBufferDatabase) -> None:
    """Same .id, different content (model_copy preserves id) must NOT merge."""
    _start_sample(db)
    msg = ChatMessageUser(content="original content")
    mutated = msg.model_copy(update={"content": "mutated content"})
    assert mutated.id == msg.id

    _log_model_event(db, [msg])
    _log_model_event(db, [msg, mutated])

    assert sorted(_pool_contents(db)) == ["mutated content", "original content"]


def test_in_place_mutation_reuses_first_pooled_version(
    db: SampleBufferDatabase,
) -> None:
    """Mutating a pooled object in place aliases history.

    The identity fast path resolves to the first-pooled version
    (documented, accepted).
    """
    _start_sample(db)
    msg = ChatMessageUser(content="version one")
    _log_model_event(db, [msg])
    msg.content = "version two"
    _log_model_event(db, [msg])

    assert _pool_contents(db) == ["version one"]


def test_rollback_restores_pool_indices(
    db: SampleBufferDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed log_events batch must unwind in-memory index state.

    SQLite and the indices must stay consistent for subsequent batches.

    Failure injection: monkeypatch to_json_str_safe (called in log_events to
    serialize the event row, AFTER _condense_event has already inserted pool
    entries and mutated the in-memory indices).  The first call during the
    failing batch raises, which triggers the on_rollback callback that must
    restore the indices to their pre-batch state.

    Note: the condensed event row contains the model output ("response") but
    NOT the message content (that lives only in pool rows).  We therefore
    fail unconditionally on the first call inside the second log_events
    invocation -- this is safe because the monkeypatch is installed only
    around that specific call.
    """
    import inspect_ai.log._recorders.buffer.database as database_module

    _start_sample(db)
    msg_a = ChatMessageUser(content="message a")
    _log_model_event(db, [msg_a])

    # Install patch: fail on the first to_json_str_safe call in this batch.
    # That call happens AFTER _condense_event mutated the indices (pool inserts
    # for msg_b ran), but BEFORE conn.execute inserts the event row.
    original = getattr(database_module, "to_json_str_safe")
    call_count = 0

    def fail_first_call(value: object) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("induced failure")
        return original(value)

    monkeypatch.setattr(database_module, "to_json_str_safe", fail_first_call)
    msg_b = ChatMessageUser(content="message b")
    with pytest.raises(RuntimeError, match="induced failure"):
        _log_model_event(db, [msg_a, msg_b])
    monkeypatch.undo()

    # guard: the injected failure fired exactly at the event-row serialization
    # (if a future to_json_str_safe call is added earlier in the batch, this
    # test would silently stop exercising the post-condense rollback path)
    assert call_count == 1

    # retry the same batch: indices were restored, so positions must align
    _log_model_event(db, [msg_a, msg_b])
    data = db.get_sample_data("s1", 1)
    assert data is not None
    assert _pool_contents(db) == ["message a", "message b"]
    last = data.events[-1].event
    assert isinstance(last, dict)
    assert last["input_refs"] == [[0, 2]]


def test_buffer_pool_dedup_break_path_uses_content_hash(
    db: SampleBufferDatabase,
) -> None:
    """On a prefix break, equal-content/different-id messages still hash-dedup.

    The second event rewrites history (drops msg_1), so it takes the break
    path, where content dedup is what protects sliding-window and bridge
    scaffolds from per-occurrence row growth.
    """
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_1 = ChatMessageUser(content="Hello").model_copy(update={"id": "uuid-aaa"})
    msg_2 = ChatMessageUser(content="Hello").model_copy(update={"id": "uuid-bbb"})
    msg_3 = ChatMessageUser(content="Other").model_copy(update={"id": "uuid-ccc"})

    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_1, msg_3]))]
    )
    # history rewritten (msg_1 dropped) -> prefix break -> hash dedup applies
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_3, msg_2]))]
    )

    data = db.get_sample_data("s1", 1)
    assert data is not None
    # msg_2 deduped against msg_1's row by content despite the different id
    assert len(data.message_pool) == 2

    last = data.events[-1].event
    assert isinstance(last, dict)
    assert last["input_refs"] == [[1, 2], [0, 1]]


def test_buffer_pool_append_path_mints_occurrence_rows(
    db: SampleBufferDatabase,
) -> None:
    """On pure append, equal-content suffix messages get their own rows."""
    sample = EvalSampleSummary(id="s1", epoch=1, input="test", target="target")
    db.start_sample(sample)

    msg_1 = ChatMessageUser(content="Hello")
    msg_2 = ChatMessageUser(content="Hello")  # fresh id, equal content

    db.log_events([SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_1]))])
    # pure append: previous input [msg_1] is a full prefix
    db.log_events(
        [SampleEvent(id="s1", epoch=1, event=_make_model_event([msg_1, msg_2]))]
    )

    data = db.get_sample_data("s1", 1)
    assert data is not None
    assert len(data.message_pool) == 2  # one row per occurrence
    last = data.events[-1].event
    assert isinstance(last, dict)
    assert last["input_refs"] == [[0, 2]]  # single monotone range
