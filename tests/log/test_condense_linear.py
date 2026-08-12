"""Regression tests for condensing correctness and complexity.

Covers:

Per-event condensing (live-eval pattern): counts content-hash invocations
while logging a growing conversation one event at a time; quadratic behavior
hashes ~N^2/2 messages, linear stays within a small multiple of N. See
inspect_ai/event/_pool_index.py for the per-event strategy.

Batch condensing (condense_sample): counts model_copy walks and pool hashes
across a full condense_sample call; both must be O(unique messages), not
O(history length). See inspect_ai/log/_condense.py walk-cache for the batch
path.

Cache isolation: asserts that the events walk and the messages walk use
separate caches so that event-walked attachment refs never leak into
sample.messages content (which must stay inline).

Dedup correctness across paths: pool rows are reused on store reopen and
buffer-to-transcript-store export (hash parity, insertion-order storage
round-trips), and prefix matching never merges python-equal but
JSON-distinct wire values (0 vs 0.0, True vs 1).

Transcript-level call walk-cache linearity: counts mm3_hash invocations (the
attachment-walk path bound in log/_condense) while driving a single growing
request lineage, several interleaved or forked lineages, and the realistic
pending/registration/completion/stamping notification shape through
Transcript and the buffer db. Also covers graceful degradation once
concurrent lineages exceed CallWalkCache's slot cap.
"""

import json
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterator

import pytest
from pydantic import JsonValue

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._validate import validate_chat_messages
from inspect_ai.log._condense import condense_events, condense_sample, expand_events
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import Transcript
from inspect_ai.log._transcript_store import TranscriptEventStore
from inspect_ai.model._chat_message import ChatMessage, ChatMessageBase, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput

N_EVENTS = 100
ATTACHABLE = "x" * 150  # > events_attachment_fn's 100-char attachment threshold


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


class AttachmentHashCounter:
    hashes: int = 0


@pytest.fixture
def attachment_hash_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AttachmentHashCounter]:
    """Count content hashes in the attachment-walk path (log/_condense binding)."""
    import inspect_ai.log._condense as condense
    from inspect_ai._util.hash import mm3_hash

    counter = AttachmentHashCounter()

    def counting(text: str) -> str:
        counter.hashes += 1
        return mm3_hash(text)

    monkeypatch.setattr(condense, "mm3_hash", counting)
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


class CopyCounter:
    copies: int = 0


@pytest.fixture
def message_copy_counter(monkeypatch: pytest.MonkeyPatch) -> Iterator[CopyCounter]:
    """Count ChatMessage.model_copy calls (== full message walks in condense)."""
    counter = CopyCounter()
    original = ChatMessageBase.model_copy

    def counting_copy(
        self: ChatMessageBase,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> ChatMessageBase:
        counter.copies += 1
        return original(self, update=update, deep=deep)

    monkeypatch.setattr(ChatMessageBase, "model_copy", counting_copy)
    yield counter


def _sample_with_growing_history(n_turns: int) -> EvalSample:
    """A sample whose ModelEvent inputs re-send the same growing history objects.

    Message content is ~250 chars (above the 100-char attachment threshold), so
    the walk rewrites every message — the case where the old cache never hit.
    Each event also carries a ModelCall with a growing wire list (fresh dicts
    each turn, like providers produce) to exercise call-pool prefix matching.
    """
    history: list[ChatMessage] = []
    wire: list[dict[str, JsonValue]] = []
    events: list[Event] = []
    for i in range(n_turns):
        content = f"user message {i:06d} " * 12
        history.append(ChatMessageUser(content=content))
        wire.append({"role": "user", "content": content})
        call_msgs: list[JsonValue] = [dict(m) for m in wire]
        event = ModelEvent(
            model="test",
            input=list(history),
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput.from_content("test", f"assistant reply {i:06d} " * 12),
            call=ModelCall(
                request={"model": "test", "messages": call_msgs},
                response={"id": "r1"},
            ),
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        events.append(event)
        history.append(event.output.message)
    return EvalSample(
        id="s1",
        epoch=1,
        input="start",
        target="done",
        messages=list(history),
        events=events,
    )


@pytest.mark.parametrize("n_turns", [100, 200])
def test_condense_sample_walk_is_linear(
    n_turns: int, hash_counter: HashCounter, message_copy_counter: CopyCounter
) -> None:
    """condense_sample full walks and pool hashes must be O(unique messages).

    Quadratic behavior walks/hashes ~n_turns^2/2 messages (>= 5000 at
    n_turns=100); linear behavior stays within a small multiple of the
    2*n_turns unique messages. Running at two sizes pins the scaling.
    """
    sample = _sample_with_growing_history(n_turns)
    condensed = condense_sample(sample)

    # full walks: each unique message is walked at most once per walk context
    # (events context + messages context), plus small constant overhead
    assert message_copy_counter.copies <= 8 * n_turns, (
        f"message walking is superlinear: {message_copy_counter.copies} "
        f"model_copy calls for {2 * n_turns} unique messages"
    )
    # pool dedup: each unique walked object hashed once via the id(obj) cache
    assert hash_counter.msg_hashes <= 6 * n_turns, (
        f"message hashing is superlinear: {hash_counter.msg_hashes} hashes "
        f"for {2 * n_turns} unique messages"
    )
    # call pool dedup: prefix-matching reuses the previous event's indices,
    # so only the divergent tail is hashed
    assert hash_counter.call_hashes <= 6 * n_turns, (
        f"call hashing is superlinear: {hash_counter.call_hashes} hashes "
        f"for {n_turns} events"
    )

    # the condensed result is still correct: all unique event-input messages
    # pooled (the last assistant message never appears in any input)
    assert condensed.events_data is not None
    assert len(condensed.events_data["messages"]) == 2 * n_turns - 1
    last_event = condensed.events[-1]
    assert isinstance(last_event, ModelEvent)
    assert last_event.input == []
    assert last_event.input_refs == [(0, 2 * n_turns - 1)]

    # call pool: one unique wire message per turn, all pooled
    assert len(condensed.events_data["calls"]) == n_turns
    assert last_event.call is not None
    assert last_event.call.call_refs == [(0, n_turns)]
    assert last_event.call.call_key == "messages"
    assert "messages" not in last_event.call.request


def test_condense_sample_rewritten_history_condenses_correctly() -> None:
    """Event inputs that are NOT prefix-extensions must still condense correctly.

    The walk cache and pool dedup are tuned for the common scaffold shape
    where each event's input extends the previous one with the same objects.
    A history rewritten mid-conversation (messages dropped/reordered, fresh
    objects with equal content) must still dedup equal content into the same
    pool entry and round-trip every event's input.
    """
    # content < 100 chars so the events walk leaves it inline and the
    # round-tripped inputs compare equal to the originals
    m0 = ChatMessageUser(content="message zero")
    m1 = ChatMessageUser(content="message one")
    # fresh object, equal content to m0 (new id): pool dedup must merge them
    m2 = ChatMessageUser(content="message zero")
    m3 = ChatMessageUser(content="message three")
    m4 = ChatMessageUser(content="message four")

    inputs: list[list[ChatMessage]] = [
        [m0],  # growing
        [m0, m1],  # growing (identical prefix)
        [m1, m2, m3],  # rewritten: reordered, m0 replaced by equal-content m2
        [m1, m2, m3, m4],  # growing again from the rewritten history
    ]
    events: list[Event] = [_model_event(list(msgs), []) for msgs in inputs]
    sample = EvalSample(
        id="s1",
        epoch=1,
        input="start",
        target="done",
        messages=[],
        events=events,
    )

    condensed = condense_sample(sample)

    # pool: m0, m1, m3, m4 (m2 deduped into m0's entry)
    assert condensed.events_data is not None
    pool = condensed.events_data["messages"]
    assert [m.content for m in pool] == [
        "message zero",
        "message one",
        "message three",
        "message four",
    ]

    # refs: event 3's input [m1, m2, m3] -> indices [1, 0, 2]
    ev3 = condensed.events[2]
    assert isinstance(ev3, ModelEvent)
    assert ev3.input == []
    assert ev3.input_refs == [(1, 2), (0, 1), (2, 3)]
    ev4 = condensed.events[3]
    assert isinstance(ev4, ModelEvent)
    assert ev4.input_refs == [(1, 2), (0, 1), (2, 4)]

    # every event's input round-trips to the original (role, content) sequence
    restored = expand_events(condensed.events, condensed.events_data)
    for original_input, restored_event in zip(inputs, restored):
        assert isinstance(restored_event, ModelEvent)
        assert [(m.role, m.content) for m in restored_event.input] == [
            (m.role, m.content) for m in original_input
        ]


def test_condense_sample_messages_stay_inline() -> None:
    """sample.messages long content must stay inline after condense_sample.

    sample.messages share objects/ids with event inputs but use different
    attachment rules (events pool long text; messages keep it inline). The
    walk's message cache must not leak event-walked results (attachment refs)
    into the sample.messages walk — they must not share a cache.
    """
    long_text = "long message content " * 10  # > 100-char attachment threshold
    msg = ChatMessageUser(content=long_text)
    event = ModelEvent(
        model="test",
        input=[msg],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test", "ok"),
    )
    sample = EvalSample(
        id="s1",
        epoch=1,
        input="start",
        target="done",
        messages=[msg],
        events=[event],
    )

    condensed = condense_sample(sample)

    # events side: the pooled message's long content became an attachment ref
    assert condensed.events_data is not None
    pooled = condensed.events_data["messages"]
    assert len(pooled) == 1
    pooled_content = pooled[0].content
    assert isinstance(pooled_content, str)
    assert pooled_content.startswith("attachment://")
    # messages side: the same message object keeps its content inline
    messages_content = condensed.messages[0].content
    assert messages_content == long_text


def test_batch_call_prefix_breaks_on_json_distinct_values() -> None:
    """Batch prefix match must not reuse a pool index for a JSON-distinct element.

    Python == conflates 0 == 0.0 and True == 1; if the batch loop in
    condense_model_event_calls used == to decide the prefix length, a wire
    message that drifts from 0.0 to 0 between events would reuse the previous
    event's pool index (which stores the 0.0-serialized bytes) and round-trip
    the wrong value.

    Repro shape:
      event 1 wire: [{"role": "user", "n": 0.0}]
      event 2 wire: [{"role": "user", "n": 0}, {"role": "user", "content": "next"}]

    The first element is python-equal (0 == 0.0) but JSON-distinct, so the
    call pool must contain THREE entries (0.0-variant, 0-variant, "next"),
    and round-tripping event 2 must restore n=0 as an int, not 0.0.
    """
    ev1 = _model_event(
        input_msgs=[ChatMessageUser(content="a")],
        call_msgs=[{"role": "user", "n": 0.0}],
    )
    ev2 = _model_event(
        input_msgs=[ChatMessageUser(content="b")],
        call_msgs=[{"role": "user", "n": 0}, {"role": "user", "content": "next"}],
    )

    condensed_events, events_data = condense_events([ev1, ev2])

    # Three distinct call-pool entries: 0.0-variant, 0-variant, "next"
    call_pool = events_data["calls"]
    assert len(call_pool) == 3, (
        f"expected 3 call-pool entries (0.0-variant, 0-variant, next) but got "
        f"{len(call_pool)}: {call_pool}"
    )

    # Round-trip event 2: first wire message must have n=0 (int), not 0.0
    restored = expand_events(condensed_events, events_data)
    ev2_restored = restored[1]
    assert isinstance(ev2_restored, ModelEvent)
    assert ev2_restored.call is not None
    wire_msgs = ev2_restored.call.request.get("messages")
    assert isinstance(wire_msgs, list) and len(wire_msgs) == 2
    first_msg = wire_msgs[0]
    assert isinstance(first_msg, dict)
    n_val = first_msg["n"]
    assert n_val == 0, f"expected n=0 but got {n_val!r}"
    assert isinstance(n_val, int) and not isinstance(n_val, bool), (
        f"expected int 0 but got {type(n_val).__name__} {n_val!r}"
    )


def test_transcript_call_condense_is_linear(
    attachment_hash_counter: AttachmentHashCounter,
) -> None:
    """_process_event's call walk must hash only new content per turn.

    Counts mm3_hash as bound by log/_condense (attachment_fn hashes every
    >100-char string it attaches); a full re-walk per notification is
    O(history) hashes per turn = quadratic.
    """
    tr = Transcript(bounded=True, resident_tail=100, log_model_api=True)
    payload = ATTACHABLE
    wire: list[dict[str, JsonValue]] = []
    for i in range(N_EVENTS):
        wire.append({"role": "user", "content": f"{payload} {i}"})
        event = _model_event(
            [ChatMessageUser(content=f"msg {i}")], [dict(m) for m in wire]
        )
        event.uuid = f"event-{i}"
        tr._event(event)
        # completion: providers re-install the raw call with a response
        event.call = ModelCall(
            request={"model": "test", "messages": [dict(m) for m in wire]},
            response={"id": f"r{i}", "content": payload},
        )
        tr._event_updated(event)
        # timestamp stamping re-notifies with the (now condensed) call
        tr._event_updated(event)

    budget = 8 * N_EVENTS
    assert attachment_hash_counter.hashes <= budget, (
        f"transcript call condense is superlinear: "
        f"{attachment_hash_counter.hashes} hashes for {N_EVENTS} events"
    )


def test_condense_model_call_interleaved_streams(
    attachment_hash_counter: AttachmentHashCounter,
) -> None:
    """Two interleaved request lineages must both keep prefix-hitting.

    Simulates a fork()/parallel-tools shape. Slot-exhaustion degradation is
    covered separately by test_buffer_condense_degrades_proportionally_beyond_slot_cap.
    """
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    payload = "stream content " * 10

    def make_call(stream: str, n: int) -> ModelCall:
        msgs = [
            {"role": "user", "content": f"{stream} {payload} {i}"} for i in range(n)
        ]
        return ModelCall.create({"model": "m", "messages": msgs}, None)

    # interleave two growing streams; after warm-up each round should hash
    # only the one new message per stream, not re-walk the shared prefix
    n_rounds = 10
    for n in range(1, n_rounds + 1):
        tr._condense_model_call(make_call("a", n))
        tr._condense_model_call(make_call("b", n))
    # linear: ~2 new messages hashed per round; a quadratic re-walk would be
    # ~2 * (n_rounds*(n_rounds+1)/2) = 110
    assert attachment_hash_counter.hashes <= 4 * n_rounds, (
        f"interleaved streams thrash the walk cache: "
        f"{attachment_hash_counter.hashes} hashes"
    )


def test_condense_model_call_forked_streams_keep_separate_lineages(
    attachment_hash_counter: AttachmentHashCounter,
) -> None:
    """Streams sharing a pre-fork prefix must keep separate walk-cache slots."""
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    payload = "fork content " * 10
    shared = [{"role": "user", "content": f"shared {payload} {i}"} for i in range(3)]

    def make_call(stream: str, n: int) -> ModelCall:
        msgs = shared + [
            {"role": "user", "content": f"{stream} {payload} {i}"} for i in range(n)
        ]
        return ModelCall.create({"model": "m", "messages": msgs}, None)

    tr._condense_model_call(make_call("a", 1))  # warm the shared prefix

    n_rounds = 8
    for n in range(2, n_rounds + 2):
        tr._condense_model_call(make_call("a", n))
        tr._condense_model_call(make_call("b", n))
    # separate lineages: ~1-2 new messages hashed per call. Merged lineages
    # re-walk the divergent tail every call: ~2 * sum(2..n_rounds+1).
    assert attachment_hash_counter.hashes <= 4 * n_rounds, (
        f"forked streams thrash the walk cache: {attachment_hash_counter.hashes} hashes"
    )


def _drive_streams(tr: Transcript, n_streams: int, rounds: int) -> None:
    """Drive `n_streams` interleaved generate streams through `tr`.

    Each round advances every stream by one turn through the realistic
    pending/registration/completion/stamping notification shape, round-robin
    across streams -- the access pattern that thrashes an LRU call-pool
    cache under-capacity (each stream's slot is the next one evicted).
    """
    payload = ATTACHABLE
    histories: list[list[ChatMessage]] = [[] for _ in range(n_streams)]
    wires: list[list[dict[str, JsonValue]]] = [[] for _ in range(n_streams)]
    for r in range(rounds):
        for s in range(n_streams):
            histories[s].append(ChatMessageUser(content=f"s{s} message {r}"))
            wires[s].append({"role": "user", "content": f"s{s} {payload} {r}"})
            event = ModelEvent(
                model="test",
                input=list(histories[s]),
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(),
                output=ModelOutput(),
                pending=True,
            )
            tr._event(event)  # 1: pending
            event.call = ModelCall(
                request={"model": "test", "messages": [dict(m) for m in wires[s]]}
            )
            tr._event_updated(event)  # 2: call registration (raw)
            event.output = ModelOutput.from_content("test", "response")
            event.call = ModelCall(
                request={"model": "test", "messages": [dict(m) for m in wires[s]]},
                response={"id": f"r{s}-{r}"},
            )
            event.pending = None
            tr._event_updated(event)  # 3: completion (raw + response)
            tr._event_updated(event)  # 4: timestamp stamping (condensed form)


def test_buffer_condense_linear_with_three_interleaved_streams(
    db: SampleBufferDatabase, hash_counter: HashCounter
) -> None:
    """Streams x 2 lineages within _CALL_WALK_SLOTS: all streams stay prefix-cached.

    Fails on a 4-slot CallPoolIndex (2-stream capacity), where round-robin
    access thrashes every lineage back to full-history re-hashing.
    """
    from inspect_ai.log._condense import _CALL_WALK_SLOTS

    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))
    tr = Transcript(bounded=True, resident_tail=100, log_model_api=True)
    tr._subscribe(lambda e: db.log_events([SampleEvent(id="s1", epoch=1, event=e)]))
    n_streams = _CALL_WALK_SLOTS // 2 - 1  # 2 lineages/stream, stays under cap
    rounds = 25
    _drive_streams(tr, n_streams, rounds)

    turns = rounds * n_streams
    budget = 12 * turns
    assert hash_counter.msg_hashes <= budget, (
        f"message hashing superlinear across {n_streams} interleaved streams: "
        f"{hash_counter.msg_hashes} for {turns} turns"
    )
    assert hash_counter.call_hashes <= budget, (
        f"call hashing superlinear across {n_streams} interleaved streams: "
        f"{hash_counter.call_hashes} for {turns} turns"
    )


def test_buffer_condense_degrades_proportionally_beyond_slot_cap(
    db: SampleBufferDatabase, hash_counter: HashCounter
) -> None:
    """Streams x 2 lineages exceeding _CALL_WALK_SLOTS.

    LRU thrashes 2 lineages' worth of full history re-hashing every turn;
    random eviction spreads the excess across lineages instead, so cost
    stays well below the thrash ceiling.
    """
    from inspect_ai.log._condense import _CALL_WALK_SLOTS

    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))
    tr = Transcript(bounded=True, resident_tail=100, log_model_api=True)
    tr._subscribe(lambda e: db.log_events([SampleEvent(id="s1", epoch=1, event=e)]))
    n_streams = _CALL_WALK_SLOTS // 2 + 1  # 2 lineages/stream, exceeds cap
    rounds = 25
    _drive_streams(tr, n_streams, rounds)

    turns = rounds * n_streams
    # LRU thrash measures ~26 call-hashes/turn at this shape; random
    # eviction measured ~11. Budget at 18/turn rejects the cliff while
    # tolerating eviction-order variance.
    assert hash_counter.call_hashes <= 18 * turns, (
        f"call hashing collapsed to LRU-thrash levels across {n_streams} "
        f"interleaved streams: {hash_counter.call_hashes} for {turns} turns"
    )
    assert hash_counter.msg_hashes <= 18 * turns, (
        f"message hashing collapsed to LRU-thrash levels across {n_streams} "
        f"interleaved streams: {hash_counter.msg_hashes} for {turns} turns"
    )


def test_buffer_condense_linear_across_notification_shape(
    db: SampleBufferDatabase, hash_counter: HashCounter
) -> None:
    """The realistic per-turn shape: pending, registration, completion, stamping.

    The buffer sees raw and transcript-condensed call forms alternately;
    prefix reuse must hold for both lineages. This guard fails on a
    single-slot CallPoolIndex (the 2026-08-11 timeout-storm mechanism)
    even though per-event condensing is individually linear.
    """
    db.start_sample(EvalSampleSummary(id="s1", epoch=1, input="in", target="t"))
    tr = Transcript(bounded=True, resident_tail=100, log_model_api=True)
    tr._subscribe(lambda e: db.log_events([SampleEvent(id="s1", epoch=1, event=e)]))

    history: list[ChatMessage] = []
    wire: list[dict[str, JsonValue]] = []
    payload = ATTACHABLE
    for i in range(N_EVENTS):
        history.append(ChatMessageUser(content=f"message {i}"))
        wire.append({"role": "user", "content": f"{payload} {i}"})
        event = ModelEvent(
            model="test",
            input=list(history),
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
            output=ModelOutput(),
            pending=True,
        )
        tr._event(event)  # 1: pending
        event.call = ModelCall(
            request={"model": "test", "messages": [dict(m) for m in wire]}
        )
        tr._event_updated(event)  # 2: call registration (raw)
        event.output = ModelOutput.from_content("test", "response")
        event.call = ModelCall(
            request={"model": "test", "messages": [dict(m) for m in wire]},
            response={"id": f"r{i}"},
        )
        event.pending = None
        tr._event_updated(event)  # 3: completion (raw + response)
        tr._event_updated(event)  # 4: timestamp stamping (condensed form)

    budget = 12 * N_EVENTS
    assert hash_counter.msg_hashes <= budget, (
        f"message hashing superlinear across notification shape: "
        f"{hash_counter.msg_hashes} for {N_EVENTS} turns"
    )
    assert hash_counter.call_hashes <= budget, (
        f"call hashing superlinear across notification shape: "
        f"{hash_counter.call_hashes} for {N_EVENTS} turns"
    )
