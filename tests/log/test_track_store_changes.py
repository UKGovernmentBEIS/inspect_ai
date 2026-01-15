"""Tests for :func:`inspect_ai.log._transcript.track_store_changes`.

We compare the existing implementation:

    before = store_jsonable(store())
    ...
    after = store_jsonable(store())

with a proposed optimisation that snapshots the store via:

    before = dict_jsonable(store()._data)
    ...
    after = dict_jsonable(store()._data)

We exercise a range of Python and Pydantic value types (mirroring how the
Store is used in practice) and assert that the emitted
``StoreEvent(changes=...)`` sequences are identical under both strategies.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Callable, ContextManager

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
# Equivalence tests for different store shapes / mutations
# ---------------------------------------------------------------------------


def test_track_store_changes_no_changes_produces_no_event() -> None:
    """If the store is unchanged inside the span, no StoreEvent is emitted."""
    store = Store()
    store.set("value", 1)

    baseline_events = _run_span_with(
        _track_store_changes_with_store_jsonable, store, lambda s: None
    )
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
        data = store._data
        data["new_key"] = "value"  # add
        data["count"] = 6  # scalar replace
        data["config"]["b"]["c"] = 10  # nested replace
        del data["config"]["a"]  # delete

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
        items: list[dict[str, object]] = store._data["items"]
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
        data = store._data
        # Delete a whole top-level subtree
        del data["root"]
        # Re-add with a different shape and add a brand new root key
        data["root"] = {"a": 2, "c": 3}
        data["new_root"] = {"y": 4}

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
        data = store._data

        # Toggle metadata flags
        flags = data["metadata"]["flags"]
        flags["debug"] = not flags["debug"]
        flags["retry"] = not flags["retry"]

        # Append/remove events
        events: list[dict[str, object]] = data["events"]
        events.append({"type": "extra", "payload": "x"})
        if events:
            events.pop(0)

        # Modify nested metadata on real ChatMessage types
        user_messages: list[ChatMessageUser] = data["user_messages"]
        if user_messages:
            m0 = user_messages[0]
            meta = m0.metadata or {}
            nested = meta.setdefault("nested", {})
            nested["k"] = "v"
            m0.metadata = meta

        # Add another score record
        scores: list[_ScoreRecord] = data["scores"]
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
def _track_store_changes_with_store_jsonable():
    """Reference implementation using the *prior* ``store_jsonable`` semantics.

    Historically, ``store_jsonable`` wrapped ``dict_jsonable(store._data)`` in an
    additional ``deepcopy``. We keep that behaviour here explicitly so that the
    tests continue to compare the new implementation against the original
    snapshot strategy, even though ``store_jsonable`` itself is now lighter.
    """
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
    """Compare StoreEvent.changes between baseline and optimised spans."""
    # Baseline: reference implementation using store_jsonable(store())
    baseline_store = build_store()
    baseline_events = _run_span_with(
        _track_store_changes_with_store_jsonable, baseline_store, mutate
    )

    # Optimised using dict_jsonable(store()._data)
    opt_store = build_store()
    opt_events = _run_span_with(track_store_changes, opt_store, mutate)

    baseline_changes = [e.changes for e in baseline_events if isinstance(e, StoreEvent)]
    opt_changes = [e.changes for e in opt_events if isinstance(e, StoreEvent)]

    assert baseline_changes == opt_changes


def test_track_store_changes_nested_spans() -> None:
    """Compare behaviour for nested spans (outer span containing an inner span)."""
    baseline_nested = _run_nested_spans(_track_store_changes_with_store_jsonable)
    opt_nested = _run_nested_spans(track_store_changes)

    assert baseline_nested == opt_nested
