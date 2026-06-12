"""Regression tests: per-event condensing must be O(new messages), not O(history).

Counts content-hash invocations while logging a growing conversation one
event at a time (the live-eval pattern). Quadratic condensing computes
~N²/2 hashes for N events; linear computes ~N. See
inspect_ai/event/_pool_index.py for the strategy.
"""

import json
import tempfile
from pathlib import Path
from typing import Generator, Iterator

import pytest
from pydantic import JsonValue

from inspect_ai.event._model import ModelEvent
from inspect_ai.event._validate import validate_chat_messages
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript_store import TranscriptEventStore
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput

N_EVENTS = 100


class HashCounter:
    msg_hashes: int = 0
    call_hashes: int = 0


@pytest.fixture
def hash_counter(monkeypatch: pytest.MonkeyPatch) -> Iterator[HashCounter]:
    """Count _msg_hash/_call_hash calls across all modules that bind them."""
    import inspect_ai.event._pool as pool

    counter = HashCounter()
    original_msg_hash = pool._msg_hash
    original_call_hash = pool._call_hash

    def counting_msg_hash(msg: ChatMessage) -> str:
        counter.msg_hashes += 1
        return original_msg_hash(msg)

    def counting_call_hash(call_msg: JsonValue) -> str:
        counter.call_hashes += 1
        return original_call_hash(call_msg)

    monkeypatch.setattr(pool, "_msg_hash", counting_msg_hash)
    monkeypatch.setattr(pool, "_call_hash", counting_call_hash)
    # all condense paths (buffer, transcript store, pool-index helper) access
    # these as _pool module attributes, so patching _pool intercepts them all
    yield counter


@pytest.fixture
def db() -> Generator[SampleBufferDatabase, None, None]:
    with tempfile.TemporaryDirectory() as db_dir:
        test_db = SampleBufferDatabase(location="test_location", db_dir=Path(db_dir))
        yield test_db
        test_db.cleanup()


def _model_event(
    input_msgs: list[ChatMessage], call_msgs: list[JsonValue]
) -> ModelEvent:
    return ModelEvent(
        model="test",
        input=input_msgs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test", "response"),
        call=ModelCall(
            request={"model": "test", "messages": call_msgs},
            response={"id": "r1"},
        ),
    )


def test_buffer_condense_is_linear(
    db: SampleBufferDatabase, hash_counter: HashCounter
) -> None:
    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))

    history: list[ChatMessage] = []
    wire: list[dict[str, JsonValue]] = []
    for i in range(N_EVENTS):
        # same objects re-sent each turn, like a real agent loop
        history.append(ChatMessageUser(content=f"message {i}"))
        wire.append({"role": "user", "content": f"message {i}"})
        # fresh wire dicts each event, like providers produce
        call_msgs: list[JsonValue] = [dict(m) for m in wire]
        db.log_events(
            [
                SampleEvent(
                    id="s1", epoch=1, event=_model_event(list(history), call_msgs)
                )
            ]
        )

    # linear: ~1 new message + ~1 new call message hashed per event.
    # quadratic computes ~N_EVENTS^2/2 = 5050 of each.
    budget = 3 * N_EVENTS
    assert hash_counter.msg_hashes <= budget, (
        f"message hashing is superlinear: {hash_counter.msg_hashes} hashes "
        f"for {N_EVENTS} events"
    )
    assert hash_counter.call_hashes <= budget, (
        f"call hashing is superlinear: {hash_counter.call_hashes} hashes "
        f"for {N_EVENTS} events"
    )

    # and the result is still correct
    data = db.get_sample_data("s1", 1)
    assert data is not None
    assert len(data.message_pool) == N_EVENTS
    assert len(data.call_pool) == N_EVENTS

    # the last event's refs must cover the full pools in order
    last_event = data.events[-1].event
    assert isinstance(last_event, dict)
    assert last_event["input"] == []
    assert last_event["input_refs"] == [[0, N_EVENTS]]
    call = last_event["call"]
    assert isinstance(call, dict)
    assert call["call_refs"] == [[0, N_EVENTS]]
    assert call["call_key"] == "messages"
    request = call["request"]
    assert isinstance(request, dict)
    assert "messages" not in request

    # pool entries resolve to the original contents in order
    pool_msgs = [json.loads(entry.data) for entry in data.message_pool]
    assert [m["content"] for m in pool_msgs] == [
        f"message {i}" for i in range(N_EVENTS)
    ]
    pool_calls = [json.loads(entry.data) for entry in data.call_pool]
    assert pool_calls == [
        {"role": "user", "content": f"message {i}"} for i in range(N_EVENTS)
    ]


def test_buffer_duplicate_content_loop_is_linear(
    db: SampleBufferDatabase, hash_counter: HashCounter
) -> None:
    """Done-loop: identical content every turn, fresh ids, history re-sent.

    Occurrence-keyed positions make this linear in turns: one pool row per
    occurrence, single-range refs per event, ~2 hashes per turn.
    """
    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))

    n_turns = 50
    history: list[ChatMessage] = []
    wire: list[dict[str, JsonValue]] = []
    for _ in range(n_turns):
        # fresh objects with fresh ids each turn, content always identical
        history.append(ChatMessageUser(content="continue"))
        history.append(ChatMessageAssistant(content="Done"))
        wire.append({"role": "user", "content": "continue"})
        wire.append({"role": "assistant", "content": "Done"})
        call_msgs: list[JsonValue] = [dict(m) for m in wire]
        db.log_events(
            [
                SampleEvent(
                    id="s1", epoch=1, event=_model_event(list(history), call_msgs)
                )
            ]
        )

    # linear hashing: ~2 message + ~2 call hashes per turn
    budget = 5 * n_turns
    assert hash_counter.msg_hashes <= budget, (
        f"message hashing is superlinear: {hash_counter.msg_hashes}"
    )
    assert hash_counter.call_hashes <= budget, (
        f"call hashing is superlinear: {hash_counter.call_hashes}"
    )

    data = db.get_sample_data("s1", 1)
    assert data is not None
    # one pool row per occurrence
    assert len(data.message_pool) == 2 * n_turns
    assert len(data.call_pool) == 2 * n_turns

    # every event's refs are a single monotone range (the storage fix)
    for i, ev in enumerate(data.events):
        event_dict = ev.event
        assert isinstance(event_dict, dict)
        k = 2 * (i + 1)
        assert event_dict["input_refs"] == [[0, k]], (
            f"event {i}: {event_dict['input_refs']}"
        )
        call = event_dict["call"]
        assert isinstance(call, dict)
        assert call["call_refs"] == [[0, k]], f"event {i}: {call['call_refs']}"

    # pool rows resolve to the original alternating contents in order
    pool_msgs = [json.loads(entry.data) for entry in data.message_pool]
    assert [m["content"] for m in pool_msgs] == ["continue", "Done"] * n_turns


def _no_attachment(_: str) -> str | None:
    return None


def test_transcript_store_condense_is_linear(
    tmp_path: Path, hash_counter: HashCounter
) -> None:
    store = TranscriptEventStore(tmp_path / "transcript_event_store.sqlite")

    history: list[ChatMessage] = []
    wire: list[dict[str, JsonValue]] = []
    for i in range(N_EVENTS):
        # same objects re-sent each turn, like a real agent loop
        history.append(ChatMessageUser(content=f"message {i}"))
        wire.append({"role": "user", "content": f"message {i}"})
        # fresh wire dicts each event, like providers produce
        call_msgs: list[JsonValue] = [dict(m) for m in wire]
        store.merge_event(_model_event(list(history), call_msgs), _no_attachment)

    # linear: ~1 new message + ~1 new call message hashed per event.
    # quadratic computes ~N_EVENTS^2/2 = 5050 of each.
    budget = 3 * N_EVENTS
    assert hash_counter.msg_hashes <= budget, (
        f"message hashing is superlinear: {hash_counter.msg_hashes} hashes "
        f"for {N_EVENTS} events"
    )
    assert hash_counter.call_hashes <= budget, (
        f"call hashing is superlinear: {hash_counter.call_hashes} hashes "
        f"for {N_EVENTS} events"
    )

    counts = store.counts()
    assert counts.message_pool == N_EVENTS
    assert counts.call_pool == N_EVENTS
    store.close()


def test_transcript_store_reopen_reuses_pool_rows(tmp_path: Path) -> None:
    """On resume the in-memory index is empty; SQLite hash lookup must dedup.

    Simulates the common resume pattern: a store is written, closed, and
    reopened in a fresh process (empty in-memory indices).  A re-parsed
    equal-content message must hit the existing pool row via the SQLite
    hash lookup rather than inserting a duplicate: pool counts stay at 2
    (msg_a deduped, msg_b new), and the second event's refs span both
    positions as a single contiguous range [[0, 2]].
    """
    db_path = tmp_path / "transcript_event_store.sqlite"
    msg_a = ChatMessageUser(content="message a")

    store = TranscriptEventStore(db_path)
    store.merge_event(_model_event([msg_a], [{"content": "a"}]), _no_attachment)
    store.close()

    # Simulate a fresh process: new store object, empty in-memory indices.
    # Re-parse msg_a from JSON so object identity differs but content matches.
    reparsed_a = ChatMessageUser.model_validate_json(msg_a.model_dump_json())
    msg_b = ChatMessageUser(content="message b")

    store2 = TranscriptEventStore(db_path)  # reset=False (default) preserves rows
    store2.merge_event(
        _model_event([reparsed_a, msg_b], [{"content": "a"}, {"content": "b"}]),
        _no_attachment,
    )

    counts = store2.counts()
    assert counts.message_pool == 2, (
        f"expected 2 pool rows (msg_a deduped, msg_b new) but got {counts.message_pool}"
    )
    assert counts.call_pool == 2, (
        f"expected 2 call-pool rows but got {counts.call_pool}"
    )

    work_dir = tmp_path / "out"
    work_dir.mkdir()
    store2.write_transcript_files(
        events_path=work_dir / "events.json",
        events_data_path=work_dir / "events_data.json",
        attachments_path=work_dir / "attachments.json",
    )
    store2.close()

    events = json.loads((work_dir / "events.json").read_text())
    # The second event (index 1) covers both pool entries [0, 2].
    assert events[1]["input_refs"] == [[0, 2]], (
        f"expected input_refs [[0, 2]] but got {events[1].get('input_refs')}"
    )
    assert events[1]["call"]["call_refs"] == [[0, 2]], (
        f"expected call_refs [[0, 2]] but got {events[1]['call'].get('call_refs')}"
    )


def test_buffer_export_to_transcript_store_hash_parity(tmp_path: Path) -> None:
    """Buffer-exported pool rows must dedup against the store's live merges.

    Drives the real ``export_transcript_events`` into a real
    ``TranscriptEventStore`` (the checkpointer seeding path).  The buffer
    stores rows with its own hash and serialization; the store's live
    condense path computes hashes from walked message objects.  If the two
    sides ever disagree (serialization key order, walked form, hash
    function), a live merge of content already exported duplicates pool
    rows.  Unsorted dict metadata is the case that catches key-order drift.
    """
    msg_a = ChatMessageUser(content="message a", metadata={"b": 1, "a": 2})
    msg_b = ChatMessageUser(content="message b")
    wire: list[dict[str, JsonValue]] = [
        {"role": "user", "content": "message a", "z": 1, "a": 2}
    ]
    wire_msgs: list[JsonValue] = list(wire)

    db = SampleBufferDatabase(location="export_parity", db_dir=tmp_path)
    try:
        db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))
        db.log_events(
            [SampleEvent(id="s1", epoch=1, event=_model_event([msg_a], wire_msgs))]
        )
        db.log_events(
            [
                SampleEvent(
                    id="s1", epoch=1, event=_model_event([msg_a, msg_b], wire_msgs)
                )
            ]
        )

        store = TranscriptEventStore(tmp_path / "transcript_event_store.sqlite")
        exported = db.export_transcript_events("s1", 1, store)
        assert exported == 2
        counts = store.counts()
        assert counts.message_pool == 2
        assert counts.call_pool == 1
    finally:
        db.cleanup()

    # live-merge equal content (fresh objects, fresh ids — only the hash can
    # dedup): pool counts must not grow if buffer and store hashes agree
    reparsed_a = ChatMessageUser.model_validate_json(msg_a.model_dump_json())
    fresh_wire: list[JsonValue] = [dict(wire[0])]
    store.merge_event(_model_event([reparsed_a], fresh_wire), _no_attachment)
    counts = store.counts()
    assert counts.message_pool == 2, (
        f"buffer-exported and live-merged hashes diverged: {counts.message_pool} rows"
    )
    assert counts.call_pool == 1, (
        f"buffer-exported and live-merged call hashes diverged: {counts.call_pool} rows"
    )
    assert counts.events == 3
    store.close()


def test_transcript_store_reseed_dedups_dict_field_messages(tmp_path: Path) -> None:
    """Stored pool bytes must re-hash to the stored hash on re-seed.

    ``_msg_hash`` hashes insertion-order serialization, so the stored pool
    JSON must use insertion order too: ``json.dumps(..., sort_keys=True)``
    would reorder dict fields (tool-call arguments, metadata), making the
    re-parsed message hash differently from its own stored row and
    inserting a duplicate on every checkpoint-resume re-seed
    (``merge_message_pool`` over hydrated pool entries).
    """
    db_path = tmp_path / "transcript_event_store.sqlite"
    # dict field whose insertion order differs from sorted order
    msg = ChatMessageUser(content="hello", metadata={"b": 1, "a": 2})

    store = TranscriptEventStore(db_path)
    store.merge_message_pool([msg])
    assert store.counts().message_pool == 1

    # export the pool the way hydration reads it back on resume
    work_dir = tmp_path / "out"
    work_dir.mkdir()
    store.write_transcript_files(
        events_path=work_dir / "events.json",
        events_data_path=work_dir / "events_data.json",
        attachments_path=work_dir / "attachments.json",
    )
    store.close()

    raw = json.loads((work_dir / "events_data.json").read_text())
    reparsed = validate_chat_messages(raw["messages"])

    # reopen (reset=False) and re-seed, like checkpointer resume does
    store2 = TranscriptEventStore(db_path)
    store2.merge_message_pool(reparsed)
    assert store2.counts().message_pool == 1, (
        "re-seeded message must dedup against its own stored row "
        f"(got {store2.counts().message_pool} rows)"
    )
    store2.close()
