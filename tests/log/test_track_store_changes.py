"""Tests for :func:`inspect_ai.log._transcript.track_store_changes`.

``track_store_changes`` defers the "before" snapshot of the store until the
store is first written or hands out a mutable value, so spans that never touch
the store serialise nothing. These tests check that the emitted
``StoreEvent(changes=...)`` sequences are identical to a reference
implementation that eagerly snapshots the store at span begin and end, across
the range of Python and Pydantic value types (and mutation styles, including
in-place mutation of values obtained via ``store.get()``) that the Store sees
in practice.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Callable, ContextManager

import pytest
from pydantic import BaseModel, Field

from inspect_ai._util.json import JsonChange
from inspect_ai.event import Event, StoreEvent
from inspect_ai.log._transcript import Transcript, init_transcript, track_store_changes
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.util import StoreModel
from inspect_ai.util._store import (
    Store,
    dict_jsonable,
    init_subtask_store,
    store_changes,
)


def test_dict_jsonable_independent_copy() -> None:
    """dict_jsonable returns a fresh JSON tree that does not share state."""
    data: dict[str, Any] = {
        "numbers": [1, 2, 3],
        "config": {"a": 1, "b": {"c": 2}},
    }

    snapshot = dict_jsonable(data)

    # Mutate original deeply
    data["numbers"].append(4)
    data["config"]["b"]["c"] = 99
    data["config"]["new"] = "x"

    assert snapshot["numbers"] == [1, 2, 3]
    assert snapshot["config"] == {"a": 1, "b": {"c": 2}}


# ---------------------------------------------------------------------------
# Lazy snapshot: untouched spans serialise nothing
# ---------------------------------------------------------------------------


@pytest.fixture
def jsonable_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count calls to ``dict_jsonable`` (the store serialisation primitive)."""
    import inspect_ai.util._store as store_module

    calls: list[int] = []
    original = store_module.dict_jsonable

    def counting(data: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        return original(data)

    monkeypatch.setattr(store_module, "dict_jsonable", counting)
    return calls


def test_untouched_span_does_not_serialise(jsonable_calls: list[int]) -> None:
    store = Store()
    store.set("payload", {"big": "x" * 1000})

    events = _run_span_with(track_store_changes, store, lambda s: None)

    assert events == []
    assert jsonable_calls == []


def test_scalar_read_does_not_serialise(jsonable_calls: list[int]) -> None:
    store = Store()
    store.set("answer", 42)
    store.set("name", "abc")

    def read(s: Store) -> None:
        assert s.get("answer") == 42
        assert s.get("name") == "abc"
        assert s.get("missing") is None
        assert "answer" in s
        assert list(s.keys()) == ["answer", "name"]

    events = _run_span_with(track_store_changes, store, read)

    assert events == []
    assert jsonable_calls == []


def test_set_emits_expected_patch(jsonable_calls: list[int]) -> None:
    store = Store()
    store.set("count", 1)

    def mutate(s: Store) -> None:
        s.set("count", 2)
        s.set("added", "x")

    events = _run_span_with(track_store_changes, store, mutate)

    store_events = [e for e in events if isinstance(e, StoreEvent)]
    assert len(store_events) == 1
    assert sorted(store_events[0].changes, key=lambda c: c.path) == [
        JsonChange(op="add", path="/added", value="x"),
        JsonChange(op="replace", path="/count", value=2, replaced=1),
    ]
    # exactly one before and one after snapshot
    assert len(jsonable_calls) == 2


def test_delete_emits_expected_patch() -> None:
    store = Store()
    store.set("gone", {"a": 1})

    events = _run_span_with(track_store_changes, store, lambda s: s.delete("gone"))

    assert [e.changes for e in events if isinstance(e, StoreEvent)] == [
        [JsonChange(op="remove", path="/gone")]
    ]


def test_in_place_mutation_via_get_is_detected() -> None:
    store = Store()
    store.set("items", [1, 2])

    events = _run_span_with(
        track_store_changes, store, lambda s: s.get("items").append(3)
    )

    assert [e.changes for e in events if isinstance(e, StoreEvent)] == [
        [JsonChange(op="add", path="/items/2", value=3)]
    ]


def test_get_with_default_inserts_and_is_detected() -> None:
    store = Store()

    def mutate(s: Store) -> None:
        history: list[str] = s.get("history", [])
        history.append("first")

    events = _run_span_with(track_store_changes, store, mutate)

    assert [e.changes for e in events if isinstance(e, StoreEvent)] == [
        [JsonChange(op="add", path="/history", value=["first"])]
    ]


def test_nested_spans_only_inner_writes() -> None:
    store = Store()
    store.set("value", 0)
    init_subtask_store(store)
    transcript = Transcript()
    init_transcript(transcript)

    with track_store_changes():
        with track_store_changes():
            store.set("value", 1)

    store_events = [e for e in transcript.events if isinstance(e, StoreEvent)]
    expected = [JsonChange(op="replace", path="/value", value=1, replaced=0)]
    # inner span emits first, then the enclosing span reports the same change
    assert [e.changes for e in store_events] == [expected, expected]


def test_untouched_span_after_touched_span_does_not_serialise(
    jsonable_calls: list[int],
) -> None:
    store = Store()
    init_subtask_store(store)
    init_transcript(Transcript())

    with track_store_changes():
        store.set("a", 1)
    assert len(jsonable_calls) == 2

    with track_store_changes():
        pass
    assert len(jsonable_calls) == 2


def test_store_model_attribute_write_and_in_place_mutation() -> None:
    class _Agent(StoreModel):
        turns: int = 0
        notes: list[str] = Field(default_factory=list)

    store = Store()
    _Agent(store=store)  # populate defaults

    def mutate(s: Store) -> None:
        model = _Agent(store=s)
        model.turns = 1
        model.notes.append("hello")

    events = _run_span_with(track_store_changes, store, mutate)

    store_events = [e for e in events if isinstance(e, StoreEvent)]
    assert len(store_events) == 1
    # jsonpatch does not order operations deterministically
    assert sorted(store_events[0].changes, key=lambda c: c.path) == [
        JsonChange(op="add", path="/_Agent:notes/0", value="hello"),
        JsonChange(op="replace", path="/_Agent:turns", value=1, replaced=0),
    ]


def test_concurrent_spans_share_snapshot_semantics() -> None:
    """A write in one task is visible to a concurrently open span in another.

    This matches the eager-snapshot behaviour: every open span diffs the whole
    store, whichever task performed the write.
    """
    store = Store()
    store.set("value", 0)
    init_subtask_store(store)
    transcript = Transcript()
    init_transcript(transcript)

    async def main() -> None:
        writer_done = asyncio.Event()
        reader_open = asyncio.Event()

        async def reader() -> None:
            with track_store_changes():
                reader_open.set()
                await writer_done.wait()

        async def writer() -> None:
            await reader_open.wait()
            with track_store_changes():
                store.set("value", 1)
            writer_done.set()

        await asyncio.gather(reader(), writer())

    asyncio.run(main())

    store_events = [e for e in transcript.events if isinstance(e, StoreEvent)]
    expected = [JsonChange(op="replace", path="/value", value=1, replaced=0)]
    assert [e.changes for e in store_events] == [expected, expected]


def test_tracker_removed_when_span_raises() -> None:
    store = Store()
    init_subtask_store(store)
    init_transcript(Transcript())

    with pytest.raises(RuntimeError):
        with track_store_changes():
            raise RuntimeError("boom")

    assert store._trackers == []


# ---------------------------------------------------------------------------
# Equivalence tests for different store shapes / mutations
# ---------------------------------------------------------------------------


def test_track_store_changes_no_changes_produces_no_event() -> None:
    """If the store is unchanged inside the span, no StoreEvent is emitted."""
    store = Store()
    store.set("value", 1)

    baseline_events = _run_span_with(_track_store_changes_eager, store, lambda s: None)
    opt_events = _run_span_with(track_store_changes, store, lambda s: None)

    assert baseline_events == opt_events == []


def test_track_store_changes_scalars_and_nested_dicts() -> None:
    """Compare behaviour for scalar and nested dict mutations."""

    def build_store() -> Store:
        s = Store()
        s.set("count", 5)
        s.set("config", {"a": 1, "b": {"c": 2}})
        return s

    def mutate(store: Store) -> None:
        store.set("new_key", "value")  # add
        store.set("count", 6)  # scalar replace
        config = store.get("config")
        config["b"]["c"] = 10  # nested replace
        del config["a"]  # delete

    _assert_store_events_equal(build_store, mutate)


def test_track_store_changes_lists_of_dicts() -> None:
    """Compare behaviour for list insert/remove/replace operations."""

    def build_store() -> Store:
        s = Store()
        s.set(
            "items",
            [
                {"id": 1, "name": "a"},
                {"id": 2, "name": "b"},
                {"id": 3, "name": "c"},
            ],
        )
        return s

    def mutate(store: Store) -> None:
        items: list[dict[str, object]] = store.get("items")
        items.insert(1, {"id": 99, "name": "x"})  # insert
        items[0] = {"id": 100, "name": "replaced"}  # replace
        items.pop()  # remove

    _assert_store_events_equal(build_store, mutate)


def test_track_store_changes_top_level_keys() -> None:
    """Compare behaviour for top-level add/remove/replace of keys."""

    def build_store() -> Store:
        s = Store()
        s.set("root", {"a": 1, "b": 2})
        s.set("other", {"x": 1})
        return s

    def mutate(store: Store) -> None:
        # Delete a whole top-level subtree
        store.delete("root")
        # Re-add with a different shape and add a brand new root key
        store.set("root", {"a": 2, "c": 3})
        store.set("new_root", {"y": 4})

    _assert_store_events_equal(build_store, mutate)


class _ScoreRecord(BaseModel):
    """Simple model used to exercise Pydantic objects in the store."""

    score: float
    feedback: str | None = None


def test_track_store_changes_message_like_store() -> None:
    """Compare behaviour for a store shaped like a real chat transcript."""

    def build_store() -> Store:
        s = Store()

        # Use real Inspect chat message types rather than ad-hoc models
        user_messages: list[ChatMessageUser] = []
        assistant_messages: list[ChatMessageAssistant] = []
        for i in range(4):
            user_messages.append(
                ChatMessageUser(
                    content=f"user msg {i}",
                    metadata={"idx": i},
                )
            )
            assistant_messages.append(
                ChatMessageAssistant(
                    content=f"assistant msg {i}",
                    metadata={"idx": i},
                )
            )

        s.set("user_messages", user_messages)
        s.set("assistant_messages", assistant_messages)
        s.set("events", [{"type": "e", "i": i} for i in range(2)])
        s.set(
            "metadata",
            {"seed": "seed", "flags": {"debug": False, "retry": True}},
        )
        s.set("scores", [_ScoreRecord(score=0.5, feedback="ok")])
        return s

    def mutate(store: Store) -> None:
        # Toggle metadata flags
        flags = store.get("metadata")["flags"]
        flags["debug"] = not flags["debug"]
        flags["retry"] = not flags["retry"]

        # Append/remove events
        events: list[dict[str, object]] = store.get("events")
        events.append({"type": "extra", "payload": "x"})
        if events:
            events.pop(0)

        # Modify nested metadata on real ChatMessage types
        user_messages: list[ChatMessageUser] = store.get("user_messages")
        if user_messages:
            m0 = user_messages[0]
            meta = m0.metadata or {}
            nested = meta.setdefault("nested", {})
            nested["k"] = "v"
            m0.metadata = meta

        # Add another score record
        scores: list[_ScoreRecord] = store.get("scores")
        scores.append(_ScoreRecord(score=0.9, feedback="better"))

    _assert_store_events_equal(build_store, mutate)


class _UserStore(StoreModel):
    """Example StoreModel used to verify Pydantic-backed store behaviour."""

    counter: int = 0
    payload: dict[str, object] = Field(default_factory=dict)


def test_track_store_changes_with_store_model() -> None:
    """Compare behaviour when mutating the store via a StoreModel."""

    def build_store() -> Store:
        s = Store()
        model = _UserStore(store=s)
        model.counter = 1
        model.payload = {"x": 1}
        return s

    def mutate(store: Store) -> None:
        model = _UserStore(store=store)
        model.counter += 1
        model.payload["y"] = 2

    _assert_store_events_equal(build_store, mutate)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _run_span_with(
    span_cm: Callable[[], ContextManager[None]],
    store: Store,
    mutate: Callable[[Store], None],
) -> list[Event]:
    """Run a span context with a fresh Transcript and Store, return events."""
    init_subtask_store(store)
    transcript = Transcript()
    init_transcript(transcript)

    with span_cm():
        mutate(store)

    return list(transcript.events)


def _run_nested_spans(
    span_cm: Callable[[], ContextManager[None]],
) -> list[list[JsonChange]]:
    """Run nested spans (outer + inner) and return StoreEvent.changes sequences."""
    store = Store()
    store.set("value", 0)

    init_subtask_store(store)
    transcript = Transcript()
    init_transcript(transcript)

    with span_cm():
        store.set("outer", 1)
        with span_cm():
            store.set("inner", 2)
        store.set("inner", 3)

    store_events = [e for e in transcript.events if isinstance(e, StoreEvent)]
    return [e.changes for e in store_events]


@contextmanager
def _track_store_changes_eager():
    """Reference implementation: eagerly deep-copy the whole store at begin and end."""
    from inspect_ai.log._transcript import transcript
    from inspect_ai.util._store import store

    before = deepcopy(dict_jsonable(store()._data))
    yield
    after = deepcopy(dict_jsonable(store()._data))
    changes = store_changes(before, after)
    if changes:
        transcript()._event(StoreEvent(changes=changes))


def _assert_store_events_equal(
    build_store: Callable[[], Store],
    mutate: Callable[[Store], None],
) -> None:
    """Compare StoreEvent.changes between the eager reference and track_store_changes."""
    baseline_store = build_store()
    baseline_events = _run_span_with(_track_store_changes_eager, baseline_store, mutate)

    opt_store = build_store()
    opt_events = _run_span_with(track_store_changes, opt_store, mutate)

    baseline_changes = [e.changes for e in baseline_events if isinstance(e, StoreEvent)]
    opt_changes = [e.changes for e in opt_events if isinstance(e, StoreEvent)]

    assert baseline_changes == opt_changes


def test_track_store_changes_nested_spans() -> None:
    """Compare behaviour for nested spans (outer span containing an inner span)."""
    baseline_nested = _run_nested_spans(_track_store_changes_eager)
    opt_nested = _run_nested_spans(track_store_changes)

    assert baseline_nested == opt_nested


# ---------------------------------------------------------------------------
# deepcopy (used by fork()) does not carry open trackers over to the copy
# ---------------------------------------------------------------------------


def test_deepcopy_drops_open_trackers() -> None:
    """A deep-copied Store has no trackers and independent data.

    `fork()` deep-copies the TaskState (and so its Store) inside a running
    span. Trackers open on the original must not be copied: a phantom tracker
    on the copy would never be ended, so every first write to the copy would
    serialise it and retain the snapshot for the copy's lifetime.
    """
    from inspect_ai.util._store import StoreChangeTracker

    original = Store({"items": [1, 2]})
    tracker = StoreChangeTracker(original)
    tracker.begin()
    try:
        assert len(original._trackers) == 1

        copied = deepcopy(original)

        assert copied._trackers == []
        assert len(original._trackers) == 1
        assert copied.get("items") == [1, 2]

        # a write to the copy neither reaches the original's data nor
        # snapshots the original's tracker
        copied.get("items").append(3)
        assert original._data["items"] == [1, 2]
        assert tracker._before is None

        # and a write to the original does not reach the copy
        original.set("other", "x")
        assert "other" not in copied
    finally:
        tracker.end()
