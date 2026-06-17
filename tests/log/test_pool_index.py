import gc
import weakref
from collections.abc import Callable, Sequence

import pytest
from pydantic import JsonValue

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._pool_index import (
    _BUCKET_CONTENT_LIMIT,
    CallPoolIndex,
    MessagePoolIndex,
    condense_model_event_with_indices,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent


def test_message_pool_index_identity_and_equality_hits() -> None:
    """Same object hits by identity; a re-parsed equal copy hits by equality."""
    index = MessagePoolIndex()
    msg = ChatMessageUser(content="hello")
    assert index.get(msg) is None
    index.add(msg, "hash-a", 0)
    assert index.get(msg) == 0
    assert index.size == 1

    clone = msg.model_copy()
    assert clone is not msg
    assert index.get(clone) == 0


def test_message_pool_index_miss_for_mutated_clone() -> None:
    """Clone-then-mutate (same id, different content) is a miss, then its own entry."""
    index = MessagePoolIndex()
    msg = ChatMessageUser(content="hello")
    mutated = msg.model_copy(update={"content": "changed"})
    assert mutated.id == msg.id
    index.add(msg, "hash-a", 0)
    assert index.get(mutated) is None
    index.add(mutated, "hash-b", 1)
    assert index.get(mutated) == 1
    assert index.get(msg) == 0
    assert index.size == 2


def test_message_pool_index_none_id_never_bucketed() -> None:
    index = MessagePoolIndex()
    msg = ChatMessageUser(content="hello")
    msg.id = None
    index.add(msg, "hash-a", 0)
    assert index.get(msg) is None  # falls to hash path
    assert index.get_by_hash("hash-a") == 0


def test_message_pool_index_hash_dedup_across_ids() -> None:
    """Same content, different id: second add maps to the same entry, size stays 1."""
    index = MessagePoolIndex()
    a = ChatMessageUser(content="same")
    b = ChatMessageUser(content="same")
    index.add(a, "hash-a", 0)
    assert index.get(b) is None
    assert index.get_by_hash("hash-a") == 0
    index.add(b, "hash-a", 0)
    assert index.get(b) == 0
    assert index.size == 1


def test_message_pool_index_mark_restore() -> None:
    index = MessagePoolIndex()
    a = ChatMessageUser(content="a")
    index.add(a, "hash-a", 0)
    mark = index.mark()
    b = ChatMessageUser(content="b")
    c = ChatMessageUser(content="same")
    d = ChatMessageUser(content="same")
    index.add(b, "hash-b", 1)
    index.add(c, "hash-c", 2)
    index.add(d, "hash-c", 2)  # bucket-only add (hash already present)
    assert index.size == 3
    index.restore(mark)
    assert index.size == 1
    assert index.get(a) == 0
    assert index.get(b) is None
    assert index.get(c) is None
    assert index.get(d) is None
    assert index.get_by_hash("hash-b") is None
    assert index.get_by_hash("hash-c") is None
    assert index.get_by_hash("hash-a") == 0


def test_call_pool_index_prefix_match() -> None:
    index = CallPoolIndex()
    first: list[JsonValue] = [{"role": "user", "content": "a"}]
    assert index.match_prefix(first) == []  # nothing to match before set_prev
    index.add_hash("h-a", 0)
    index.set_prev(first, [0])

    second: list[JsonValue] = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    assert index.match_prefix(second) == [0]  # equal-by-value, not identity
    index.add_hash("h-b", 1)
    index.set_prev(second, [0, 1])
    assert index.match_prefix(second) == [0, 1]


def test_call_pool_index_prefix_breaks_on_mismatch() -> None:
    index = CallPoolIndex()
    index.set_prev(
        [{"content": "a"}, {"content": "b"}, {"content": "c"}],
        [0, 1, 2],
    )
    # element 1 differs -> only index 0 reused, regardless of later equality
    result: list[JsonValue] = [{"content": "a"}, {"content": "X"}, {"content": "c"}]
    assert index.match_prefix(result) == [0]
    # new list shorter than prev: fine
    short: list[JsonValue] = [{"content": "a"}]
    assert index.match_prefix(short) == [0]


def test_call_pool_index_mark_restore() -> None:
    index = CallPoolIndex()
    index.add_hash("h-a", 0)
    prev_one: list[JsonValue] = [{"content": "a"}]
    index.set_prev(prev_one, [0])
    mark = index.mark()

    index.add_hash("h-b", 1)
    index.add_hash("h-b", 1)  # duplicate add is a no-op
    prev_two: list[JsonValue] = [{"content": "a"}, {"content": "b"}]
    index.set_prev(prev_two, [0, 1])
    assert index.size == 2

    index.restore(mark)
    assert index.size == 1
    assert index.get_by_hash("h-b") is None
    assert index.get_by_hash("h-a") == 0
    # prefix state is dropped on restore (accelerator-only; a miss is safe,
    # a stale ref to a rolled-back row is not)
    after_restore: list[JsonValue] = [{"content": "a"}, {"content": "b"}]
    assert index.match_prefix(after_restore) == []
    # and the next set_prev/match_prefix cycle works normally
    index.set_prev(after_restore, [0, 1])
    assert index.match_prefix(after_restore) == [0, 1]


def test_message_pool_index_restore_idempotent_and_mark_reusable() -> None:
    index = MessagePoolIndex()
    a = ChatMessageUser(content="a")
    index.add(a, "hash-a", 0)
    mark = index.mark()

    b = ChatMessageUser(content="b")
    index.add(b, "hash-b", 1)
    index.restore(mark)
    index.restore(mark)  # second restore with same mark: no-op
    assert index.size == 1

    # mark reuse after restore (the SQLite-retry pattern)
    c = ChatMessageUser(content="c")
    index.add(c, "hash-c", 1)
    index.restore(mark)
    assert index.size == 1
    assert index.get(c) is None
    assert index.get(a) == 0


def test_message_pool_index_restore_pops_only_post_mark_bucket_entry() -> None:
    """A bucket holding a pre-mark entry and a post-mark clone keeps the former."""
    index = MessagePoolIndex()
    msg = ChatMessageUser(content="original")
    index.add(msg, "hash-orig", 0)
    mark = index.mark()

    mutated = msg.model_copy(update={"content": "mutated"})
    index.add(mutated, "hash-mut", 1)
    assert index.get(mutated) == 1
    index.restore(mark)
    assert index.get(msg) == 0
    assert index.get(mutated) is None
    assert index.get_by_hash("hash-mut") is None


def test_call_pool_index_set_prev_copies_input() -> None:
    """Caller-side mutation after set_prev must not corrupt prefix matching."""
    index = CallPoolIndex()
    msgs: list[JsonValue] = [{"content": "a"}]
    indices = [0]
    index.set_prev(msgs, indices)
    msgs.append({"content": "b"})
    indices.append(99)
    query: list[JsonValue] = [{"content": "a"}, {"content": "b"}]
    assert index.match_prefix(query) == [0]


def test_call_pool_index_set_prev_snapshots_message_values() -> None:
    """In-place mutation of a retained wire message must not match a later event.

    The retained values are what the next event's prefix is matched against;
    if they aliased the caller's dicts, mutating one in place to equal new
    content would match the prefix against content that was never pooled at
    that position, returning a stale pool index for genuinely new content.
    """
    index = CallPoolIndex()
    msg: dict[str, JsonValue] = {"role": "user", "content": "a"}
    index.set_prev([msg], [0])
    # mutate the very dict that was handed to set_prev (the object an eval
    # mutates when it edits an already-logged call.request in place)
    msg["content"] = "b"
    # a new event whose content equals the mutated value must NOT match the
    # prefix: position 0 pooled "a", not "b"
    assert index.match_prefix([{"role": "user", "content": "b"}]) == []
    # and the genuine re-send of the originally pooled value still matches
    assert index.match_prefix([{"role": "user", "content": "a"}]) == [0]


def test_call_pool_index_carry_forward_only_snapshots_divergent_tail() -> None:
    """Carry-forward reuses prior snapshots for the matched prefix.

    The hot path passes the matched prefix length so only the divergent tail
    is snapshotted; the reused prefix snapshots stay immutable (proven by the
    in-place-mutation guard above also holding across a carry-forward).
    """
    index = CallPoolIndex()
    first: list[JsonValue] = [{"role": "user", "content": "a"}]
    index.set_prev(first, [0])

    second: list[dict[str, JsonValue]] = [
        {"role": "user", "content": "a"},  # shared prefix (matched, carried)
        {"role": "assistant", "content": "b"},  # divergent tail (snapshotted)
    ]
    prefix = index.match_prefix(second)
    assert prefix == [0]
    index.set_prev(second, [0, 1], prefix_len=len(prefix))

    # mutating the tail dict that was just snapshotted must not leak in
    second[1]["content"] = "c"
    assert index.match_prefix(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "c"}]
    ) == [0]
    # the snapshotted tail value still matches its real re-send
    assert index.match_prefix(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    ) == [0, 1]


# ---------------------------------------------------------------------------
# condense_model_event_with_indices tests
# ---------------------------------------------------------------------------


def _model_event(
    input_msgs: Sequence[ChatMessage], call_msgs: list[JsonValue] | None = None
) -> ModelEvent:
    event = ModelEvent(
        model="test",
        input=list(input_msgs),
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test", "response"),
    )
    if call_msgs is not None:
        event = event.model_copy(
            update={
                "call": ModelCall(
                    request={"model": "test", "messages": call_msgs},
                    response={"id": "r1"},
                )
            }
        )
    return event


class _Recorder:
    """Persistence callbacks that count invocations and assign positions."""

    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self.calls: list[JsonValue] = []
        self.walked_messages = 0
        self.walked_calls = 0

    def walk_message(self, msg: ChatMessage) -> ChatMessage:
        self.walked_messages += 1
        return msg.model_copy()

    def walk_call_message(self, msg: JsonValue) -> JsonValue:
        self.walked_calls += 1
        return msg

    def add_message(self, hash_value: str, walked: ChatMessage) -> int:
        self.messages.append(walked)
        return len(self.messages) - 1

    def add_call(self, hash_value: str, walked: JsonValue) -> int:
        self.calls.append(walked)
        return len(self.calls) - 1


def _condense(
    event: ModelEvent,
    msg_index: MessagePoolIndex,
    call_index: CallPoolIndex,
    recorder: _Recorder,
) -> ModelEvent:
    return condense_model_event_with_indices(
        event,
        messages=msg_index,
        calls=call_index,
        walk_message=recorder.walk_message,
        walk_call_message=recorder.walk_call_message,
        add_message=recorder.add_message,
        add_call=recorder.add_call,
    )


def test_condense_helper_walks_only_new_messages() -> None:
    msg_index = MessagePoolIndex()
    call_index = CallPoolIndex()
    recorder = _Recorder()

    history = [ChatMessageUser(content=f"msg {i}") for i in range(10)]
    for k in range(1, 11):
        event = _condense(_model_event(history[:k]), msg_index, call_index, recorder)
        assert event.input == []
        assert event.input_refs == [(0, k)]

    # 10 unique messages: walked and pooled exactly once each, despite
    # 55 message occurrences across the 10 events
    assert recorder.walked_messages == 10
    assert len(recorder.messages) == 10


def test_condense_helper_call_prefix_diff() -> None:
    msg_index = MessagePoolIndex()
    call_index = CallPoolIndex()
    recorder = _Recorder()

    wire: list[dict[str, JsonValue]] = [
        {"role": "user", "content": f"m{i}"} for i in range(10)
    ]
    for k in range(1, 11):
        # fresh dict objects each event, like providers produce
        msgs: list[JsonValue] = [dict(m) for m in wire[:k]]
        event = _condense(
            _model_event([], call_msgs=msgs), msg_index, call_index, recorder
        )
        assert event.call is not None
        assert event.call.call_refs == [(0, k)]
        assert event.call.call_key == "messages"
        assert "messages" not in event.call.request

    assert recorder.walked_calls == 10
    assert len(recorder.calls) == 10


def test_condense_helper_preserves_passthrough_cases() -> None:
    msg_index = MessagePoolIndex()
    call_index = CallPoolIndex()
    recorder = _Recorder()

    # empty input, no call -> unchanged
    event = _model_event([])
    result = _condense(event, msg_index, call_index, recorder)
    assert result.input == [] and result.input_refs is None
    assert recorder.walked_messages == 0

    # already-condensed input refs -> untouched
    condensed = _model_event([]).model_copy(update={"input_refs": [(0, 3)]})
    result = _condense(condensed, msg_index, call_index, recorder)
    assert result.input_refs == [(0, 3)]

    # call with call_refs already set -> untouched
    event = _model_event([], call_msgs=[{"content": "x"}])
    assert event.call is not None
    pre = event.call.model_copy(update={"call_refs": [(0, 1)], "request": {}})
    event = event.model_copy(update={"call": pre})
    result = _condense(event, msg_index, call_index, recorder)
    assert result.call is not None and result.call.call_refs == [(0, 1)]
    assert recorder.walked_calls == 0


def test_condense_helper_duplicate_message_in_one_event() -> None:
    msg_index = MessagePoolIndex()
    call_index = CallPoolIndex()
    recorder = _Recorder()

    msg = ChatMessageUser(content="dup")
    event = _condense(_model_event([msg, msg]), msg_index, call_index, recorder)
    assert event.input_refs == [(0, 1), (0, 1)]
    assert len(recorder.messages) == 1


def test_condense_helper_fresh_ids_bounded_index() -> None:
    """Fresh objects/ids each turn (bridge-style agents) must not grow the index.

    The identity bucket must stay bounded at the number of unique pool entries,
    not grow with the number of events.
    """
    msg_index = MessagePoolIndex()
    call_index = CallPoolIndex()
    recorder = _Recorder()

    n = 20
    for k in range(1, n + 1):
        # Rebuild full history with fresh objects and fresh ids each event,
        # simulating bridge-style scaffolds that never reuse message objects.
        history = [ChatMessageUser(content=f"msg {i}") for i in range(k)]
        _condense(_model_event(history), msg_index, call_index, recorder)

    assert len(recorder.messages) == n  # content-deduped in the pool
    assert msg_index.size == n
    # White-box: identity buckets must not accumulate one entry per occurrence;
    # each unique message should produce exactly one bucket entry.
    assert sum(len(b) for b in msg_index._buckets.values()) == n


def _heavy_image_message() -> ChatMessageUser:
    payload = "data:image/png;base64," + "A" * (_BUCKET_CONTENT_LIMIT + 1)
    return ChatMessageUser(
        content=[ContentText(text="look at this"), ContentImage(image=payload)]
    )


def _assert_not_pinned(make_msg: Callable[[], ChatMessage]) -> None:
    """Add a heavy message to a fresh index and prove it isn't retained.

    Takes a factory rather than the message itself: a message passed as an
    argument stays referenced from the caller's frame (and from pytest's
    assertion-rewriting temporaries) on some Python versions, which would
    make the weakref check fail even when the index itself holds nothing.
    The add/lookup asserts run in an inner frame that has exited before
    the collection check.
    """
    index = MessagePoolIndex()

    def add_and_check() -> "weakref.ref[ChatMessage]":
        msg = make_msg()
        ref = weakref.ref(msg)
        index.add(msg, "hash-heavy", 0)
        assert index.get(msg) is None, "heavy message was bucketed"
        assert index.get_by_hash("hash-heavy") == 0
        return ref

    ref = add_and_check()
    gc.collect()
    assert ref() is None, "index retained a reference to the heavy message"


def test_heavy_tool_call_arguments_not_pinned() -> None:
    """String content must not short-circuit the gate past tool-call payloads.

    Regression: an assistant message with short string content and a
    multi-MB tool-call argument measured as len(content) and was bucketed,
    pinning the payload.
    """
    _assert_not_pinned(
        lambda: ChatMessageAssistant(
            content="ok",
            tool_calls=[
                ToolCall(
                    id="1",
                    function="f",
                    arguments={"data": "X" * (_BUCKET_CONTENT_LIMIT + 1)},
                )
            ],
        )
    )


def test_heavy_tool_call_view_not_pinned() -> None:
    """Heavy ToolCallContent views nested inside tool calls are measured.

    Regression: the field-enumerating gate measured only
    ``tool_call.arguments``, so a heavy ``view.content`` slipped past it.
    """
    _assert_not_pinned(
        lambda: ChatMessageAssistant(
            content="ok",
            tool_calls=[
                ToolCall(
                    id="1",
                    function="f",
                    arguments={},
                    view=ToolCallContent(
                        format="markdown",
                        content="Y" * (_BUCKET_CONTENT_LIMIT + 1),
                    ),
                )
            ],
        )
    )


def test_cyclic_metadata_does_not_crash_gate() -> None:
    """Arbitrary metadata can be cyclic or deeply nested; the scan must cap.

    Cap-out reports heavy (not bucketed) — the safe, conservative
    direction. Hash dedup still works.
    """
    cyclic: dict = {"a": 1}
    cyclic["self"] = cyclic
    msg = ChatMessageUser(content="hi", metadata=cyclic)

    index = MessagePoolIndex()
    index.add(msg, "hash-cyc", 0)
    assert index.get_by_hash("hash-cyc") == 0
    # cap-out must report heavy: a payload nested below the scan depth
    # would otherwise be bucketed and pinned
    assert index.get(msg) is None


def test_message_pool_index_does_not_pin_heavy_messages() -> None:
    """Messages with media-scale content must not be retained by the index.

    Bucketed pre-walk objects are pinned for the sample's lifetime; for
    base64 payloads that re-accumulates the memory bounded transcripts
    (INSPECT_TRANSCRIPT_BOUNDED) exist to evict. Heavy messages are
    recorded in the hash index only.
    """
    _assert_not_pinned(_heavy_image_message)


def test_message_pool_index_heavy_add_mark_restore() -> None:
    """Hash-only (unbucketed) adds must unwind cleanly on restore."""
    index = MessagePoolIndex()
    light = ChatMessageUser(content="light")
    index.add(light, "hash-light", 0)
    mark = index.mark()

    heavy = _heavy_image_message()
    index.add(heavy, "hash-heavy", 1)
    assert index.size == 2
    assert index.get(heavy) is None  # hash-only: heavy is never bucketed

    index.restore(mark)
    assert index.size == 1
    assert index.get_by_hash("hash-heavy") is None
    assert index.get(light) == 0


def test_condense_helper_heavy_message_dedups_via_hash_path() -> None:
    """A heavy message re-sent across events pools once via hash dedup."""
    msg_index = MessagePoolIndex()
    call_index = CallPoolIndex()
    recorder = _Recorder()

    heavy = _heavy_image_message()
    light = ChatMessageUser(content="hello")

    first = _condense(_model_event([heavy]), msg_index, call_index, recorder)
    assert first.input_refs == [(0, 1)]
    second = _condense(_model_event([heavy, light]), msg_index, call_index, recorder)
    assert second.input_refs == [(0, 2)]

    # heavy message pooled once but re-walked on the second event
    # (the deliberate cost of not pinning it)
    assert len(recorder.messages) == 2
    assert recorder.walked_messages == 3


# ---------------------------------------------------------------------------
# Serialization-equivalent equality (== conflates 0/0.0 and True/1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first,second",
    [({"n": 0}, {"n": 0.0}), ({"flag": True}, {"flag": 1})],
    ids=["int-vs-float", "bool-vs-int"],
)
def test_message_index_distinguishes_json_distinct_metadata(
    first: dict[str, JsonValue], second: dict[str, JsonValue]
) -> None:
    """Python-equal but JSON-distinct metadata must not merge.

    The values hash differently (json.dumps emits different bytes), so a
    merge would reuse a pool entry whose stored bytes round-trip to the
    other value — silent data corruption.
    """
    msg = ChatMessageUser(content="hi", metadata=dict(first))
    variant = msg.model_copy(update={"metadata": dict(second)})
    assert msg == variant  # python equality conflates them...

    index = MessagePoolIndex()
    index.add(msg, "hash-first", 0)
    assert index.get(variant) is None  # ...the index must not
    assert index.get(msg) == 0  # true re-send still hits


@pytest.mark.parametrize(
    "first,second",
    [
        ({"role": "user", "tokens": 0}, {"role": "user", "tokens": 0.0}),
        ({"role": "user", "ok": True}, {"role": "user", "ok": 1}),
    ],
    ids=["int-vs-float", "bool-vs-int"],
)
def test_call_prefix_breaks_on_json_distinct_values(
    first: dict[str, JsonValue], second: dict[str, JsonValue]
) -> None:
    """Python-equal, JSON-distinct prefix drift must break the match.

    Reusing the prior pool index would round-trip the old value.
    """
    index = CallPoolIndex()
    index.add_hash("h-first", 0)
    index.set_prev([first], [0])
    assert index.match_prefix([dict(first)]) == [0]  # equal-by-value still matches
    assert index.match_prefix([second]) == []  # json-distinct must not


def test_strict_eq_distinguishes_json_distinct_dict_keys() -> None:
    """Key-axis conflation: {0: x} and {0.0: x} serialize differently.

    Dict lookup matches keys by ==, so the value-axis type gate alone
    would merge messages whose metadata dicts differ only in numeric/bool
    key type — the same corruption class as values, on keys.
    """
    base = ChatMessageUser(content="hi", metadata={"k": {0: "x"}})
    variant = base.model_copy(update={"metadata": {"k": {0.0: "x"}}})
    assert base == variant  # python equality conflates them...

    index = MessagePoolIndex()
    index.add(base, "hash-first", 0)
    assert index.get(variant) is None  # ...the index must not
    assert index.get(base) == 0
    # bool/int key conflation too
    b1 = ChatMessageUser(content="hi", metadata={"k": {True: "x"}})
    b2 = b1.model_copy(update={"metadata": {"k": {1: "x"}}})
    index2 = MessagePoolIndex()
    index2.add(b1, "hash-b1", 0)
    assert index2.get(b2) is None
