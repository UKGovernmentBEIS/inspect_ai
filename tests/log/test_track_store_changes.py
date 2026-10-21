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

import json
import logging
import math
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Callable, ContextManager

import anyio
import pytest
from pydantic import BaseModel, Field

from inspect_ai._util.json import JsonChange
from inspect_ai.agent._human.state import HumanAgentState, IntermediateScoring
from inspect_ai.event import Event, SpanEndEvent, StoreEvent
from inspect_ai.log import EvalSample
from inspect_ai.log._transcript import Transcript, init_transcript, track_store_changes
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.scorer import Score
from inspect_ai.util import StoreModel, current_span_id, span, subtask
from inspect_ai.util._store import (
    Store,
    dict_jsonable,
    init_subtask_store,
    store,
    store_changes,
    store_from_events,
    store_jsonable,
    suspend_store_events,
)

NAN = float("nan")


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


def test_store_changes_unchanged_nan_reports_no_change() -> None:
    """Re-serializing a NaN (in a StoreModel or a plain list) is not a change."""
    store = Store()
    state = HumanAgentState(instructions="t", store=store)
    state.scorings = [
        IntermediateScoring(time=1.0, scores=[Score(value=[float("nan"), 1.0])])
    ]
    store.set("values", [float("nan"), float("inf"), float("-inf")])

    assert store_changes(store_jsonable(store), store_jsonable(store)) is None
    assert store_changes(store, store) is None
    assert _run_span_with(track_store_changes, store, lambda s: None) == []


def test_store_changes_reports_change_to_nan() -> None:
    store = Store()
    store.set("values", [float("nan"), 1.0])

    events = _run_span_with(
        track_store_changes, store, lambda s: s.set("values", [float("nan"), NAN])
    )

    store_events = [e for e in events if isinstance(e, StoreEvent)]
    assert len(store_events) == 1
    changes = store_events[0].changes
    assert [(c.op, c.path, c.replaced) for c in changes] == [
        ("replace", "/values/1", 1.0)
    ]
    assert isinstance(changes[0].value, float) and math.isnan(changes[0].value)


def test_store_changes_reports_change_beside_unchanged_nan() -> None:
    store = Store()
    store.set("items", [{"score": float("nan"), "done": 1}])

    events = _run_span_with(
        track_store_changes,
        store,
        lambda s: s.set("items", [{"score": float("nan"), "done": True}]),
    )

    store_events = [e for e in events if isinstance(e, StoreEvent)]
    assert len(store_events) == 1
    assert [(c.op, c.path, c.value, c.replaced) for c in store_events[0].changes] == [
        ("replace", "/items/0/done", True, 1)
    ]


@pytest.mark.parametrize(
    "before,after",
    [
        ({"a": [NAN, {}]}, {"a": [0, {"x": float("nan")}]}),
        ({"a": [NAN, [0]]}, {"a": ["text", [float("nan")]]}),
    ],
)
def test_store_changes_with_nan_replay_from_logged_events(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    """StoreEvents with NaNs rebuild the final store, also after a log round trip."""
    events: list[Event] = []
    for changes in [store_changes({}, before), store_changes(before, after)]:
        assert changes is not None
        events.append(StoreEvent(changes=changes))
    sample = EvalSample(id=1, epoch=1, input="x", target="y", events=events)
    logged = EvalSample.model_validate_json(sample.model_dump_json())

    for replay_events in [events, logged.events]:
        replayed = store_from_events(replay_events)._data
        assert json.dumps(replayed) == json.dumps(after)


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


# ---------------------------------------------------------------------------
# Spans whose body raises
# ---------------------------------------------------------------------------


def _init_span_test() -> Transcript:
    init_subtask_store(Store())
    transcript = Transcript()
    init_transcript(transcript)
    return transcript


def _assert_store_event_inside_span(
    events: list[Event], span_id: str | None, changes: list[tuple[str, str, Any]]
) -> None:
    store_events = [e for e in events if isinstance(e, StoreEvent)]
    assert len(store_events) == 1
    assert store_events[0].span_id == span_id
    assert [(c.op, c.path, c.value) for c in store_events[0].changes] == changes
    end_index = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, SpanEndEvent) and e.id == span_id
    )
    assert events.index(store_events[0]) < end_index


async def test_span_that_raises_logs_store_changes() -> None:
    transcript = _init_span_test()
    error = RuntimeError("boom")
    span_id: str | None = None

    with pytest.raises(RuntimeError) as raised:
        async with span("failing"):
            span_id = current_span_id()
            store().set("key", "value")
            raise error

    assert raised.value is error
    _assert_store_event_inside_span(
        list(transcript.events), span_id, [("add", "/key", "value")]
    )


async def test_cancelled_span_logs_store_changes() -> None:
    transcript = _init_span_test()
    span_id: str | None = None

    with anyio.CancelScope() as scope:
        async with span("cancelled"):
            span_id = current_span_id()
            store().set("key", "value")
            scope.cancel()
            await anyio.sleep(10)

    assert scope.cancelled_caught
    _assert_store_event_inside_span(
        list(transcript.events), span_id, [("add", "/key", "value")]
    )


async def test_span_that_raises_without_changes_logs_no_store_event() -> None:
    transcript = _init_span_test()

    with pytest.raises(RuntimeError):
        async with span("failing"):
            raise RuntimeError("boom")

    assert not any(isinstance(e, StoreEvent) for e in transcript.events)
    assert any(isinstance(e, SpanEndEvent) for e in transcript.events)


async def test_span_store_diff_failure_does_not_mask_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    transcript = _init_span_test()
    error = RuntimeError("boom")

    def failing_store_changes(*args: Any) -> None:
        raise ValueError("diff failed")

    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_changes", failing_store_changes
    )

    with pytest.raises(RuntimeError) as raised:
        async with span("failing"):
            store().set("key", "value")
            raise error

    assert raised.value is error
    assert "diff failed" in caplog.text
    assert not any(isinstance(e, StoreEvent) for e in transcript.events)
    assert any(isinstance(e, SpanEndEvent) for e in transcript.events)


class _CleanupInterrupt(BaseException):
    pass


class _FailingHandler(logging.Handler):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error
        self.emits = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.emits += 1
        raise self.error


@pytest.mark.parametrize(
    "diff_error,handler_error",
    [
        (ValueError("diff failed"), ValueError("handler failed")),
        (_CleanupInterrupt("diff failed"), None),
        (ValueError("diff failed"), _CleanupInterrupt("handler failed")),
    ],
    ids=["handler", "diff-base-exception", "handler-base-exception"],
)
@pytest.mark.parametrize("exit", ["raise", "cancel"])
async def test_span_cleanup_failure_does_not_mask_exception(
    exit: str,
    diff_error: BaseException,
    handler_error: BaseException | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transcript = _init_span_test()
    error = RuntimeError("boom")
    diff_calls = 0

    def failing_store_changes(*args: Any) -> None:
        nonlocal diff_calls
        diff_calls += 1
        raise diff_error

    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_changes", failing_store_changes
    )
    logger = logging.getLogger("inspect_ai.log._transcript")
    handler = _FailingHandler(handler_error) if handler_error else None
    if handler is not None:
        logger.addHandler(handler)
    try:
        if exit == "raise":
            with pytest.raises(RuntimeError) as raised:
                async with span("failing"):
                    store().set("key", "value")
                    raise error
            assert raised.value is error
        else:
            with anyio.CancelScope() as scope:
                async with span("cancelled"):
                    store().set("key", "value")
                    scope.cancel()
                    await anyio.sleep(10)
            assert scope.cancelled_caught
    finally:
        if handler is not None:
            logger.removeHandler(handler)

    assert diff_calls == 1
    if handler is not None:
        assert handler.emits == 1
    else:
        assert "Unable to log store changes for span" in caplog.text
    assert any(isinstance(e, SpanEndEvent) for e in transcript.events)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("stage", ["diff", "handler"])
def test_store_changes_interrupt_during_cleanup_propagates(
    stage: str,
    interrupt: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # synchronous: a KeyboardInterrupt escaping an event loop task would
    # stop the test run rather than reach pytest.raises
    _init_span_test()
    error = RuntimeError("boom")
    raised_interrupt = interrupt()

    def failing_store_changes(*args: Any) -> None:
        raise raised_interrupt if stage == "diff" else ValueError("diff failed")

    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_changes", failing_store_changes
    )
    logger = logging.getLogger("inspect_ai.log._transcript")
    handler = _FailingHandler(raised_interrupt) if stage == "handler" else None
    if handler is not None:
        logger.addHandler(handler)
    try:
        with pytest.raises(interrupt) as raised:
            with track_store_changes():
                store().set("key", "value")
                raise error
    finally:
        if handler is not None:
            logger.removeHandler(handler)

    assert raised.value is raised_interrupt
    if handler is not None:
        assert handler.emits == 1


async def test_span_finalized_in_another_context_logs_no_store_event() -> None:
    _init_span_test()
    span_cm = span("abandoned")
    await span_cm.__aenter__()
    store().set("key", "value")

    # an abandoned span generator finalized where another store and
    # transcript are current
    other = _init_span_test()
    store().set("other", "value")
    await span_cm.gen.aclose()

    assert not any(isinstance(e, StoreEvent) for e in other.events)


# ---------------------------------------------------------------------------
# suspend_store_events()
# ---------------------------------------------------------------------------


def _fresh_transcript() -> Transcript:
    init_subtask_store(Store())
    transcript = Transcript()
    init_transcript(transcript)
    return transcript


def _store_events(transcript: Transcript) -> list[StoreEvent]:
    return [e for e in transcript.events if isinstance(e, StoreEvent)]


async def test_suspend_store_events_enclosing_span_records_net_change_once() -> None:
    """Spans inside the switch log nothing; the enclosing span logs the net change."""
    transcript = _fresh_transcript()

    async def member(name: str) -> None:
        async with span(name):
            store().set(name, True)

    async with span("team"):
        team_id = current_span_id()
        with suspend_store_events():
            async with anyio.create_task_group() as tg:
                tg.start_soon(member, "a")
                tg.start_soon(member, "b")

    store_events = _store_events(transcript)
    assert len(store_events) == 1
    assert store_events[0].span_id == team_id
    assert store_from_events(list(transcript.events))._data == {"a": True, "b": True}


async def test_suspend_store_events_subtask_store_has_no_store_events() -> None:
    """A subtask's own store logs nothing; the enclosing span logs only its store."""
    transcript = _fresh_transcript()

    @subtask("child")
    async def child() -> None:
        store().set("child", 1)

    async with span("parent"):
        parent_id = current_span_id()
        with suspend_store_events():
            store().set("parent", 1)
            await child()

    store_events = _store_events(transcript)
    assert [[c.path for c in e.changes] for e in store_events] == [["/parent"]]
    assert store_events[0].span_id == parent_id
    assert store_from_events(list(transcript.events))._data == {"parent": 1}


async def test_suspend_store_events_skips_store_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spans entered inside the switch never serialize the store."""
    _fresh_transcript()
    calls: list[None] = []

    def counting_store_jsonable(s: Store) -> dict[str, Any]:
        calls.append(None)
        return store_jsonable(s)

    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_jsonable", counting_store_jsonable
    )

    with suspend_store_events():
        async with span("inner"):
            store().set("key", 1)
    assert calls == []

    async with span("outer"):
        pass
    assert len(calls) == 2


async def test_suspend_store_events_inherited_by_tasks_started_inside() -> None:
    """Tasks started inside the switch inherit it; tasks started before do not."""
    transcript = _fresh_transcript()
    suspended = anyio.Event()

    async def started_outside() -> None:
        await suspended.wait()
        async with span("outside"):
            store().set("outside", 1)

    async def started_inside() -> None:
        async with span("inside"):
            store().set("inside", 1)

    async with anyio.create_task_group() as outer_tg:
        outer_tg.start_soon(started_outside)
        with suspend_store_events():
            async with anyio.create_task_group() as tg:
                tg.start_soon(started_inside)
            suspended.set()

    store_events = _store_events(transcript)
    assert [[c.path for c in e.changes] for e in store_events] == [["/outside"]]


async def test_suspend_store_events_nesting_and_exit_restore_tracking() -> None:
    """Exiting a nested switch keeps tracking off; exiting the outer one restores it."""
    transcript = _fresh_transcript()

    with suspend_store_events():
        with suspend_store_events():
            pass
        async with span("still suspended"):
            store().set("suspended", 1)
    async with span("tracked"):
        store().set("tracked", 1)

    with pytest.raises(RuntimeError):
        with suspend_store_events():
            raise RuntimeError()
    async with span("tracked after error"):
        store().set("after_error", 1)

    store_events = _store_events(transcript)
    assert [[c.path for c in e.changes] for e in store_events] == [
        ["/tracked"],
        ["/after_error"],
    ]
