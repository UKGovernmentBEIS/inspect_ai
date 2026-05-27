"""Tests for store_from_events() and store_from_events_as().

These functions reconstruct Store/StoreModel instances from event lists
by replaying StoreEvent changes.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from inspect_ai import Task, eval
from inspect_ai._util.json import JsonChange
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, SpanBeginEvent, SpanEndEvent, StoreEvent
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    StoreModel,
    store_as,
    store_from_events,
    store_from_events_as,
)


def _make_store_event(
    changes: list[dict[str, Any]], span_id: str | None = None
) -> StoreEvent:
    """Helper to create StoreEvent with JsonChange objects."""
    json_changes = [JsonChange(**c) for c in changes]
    return StoreEvent(changes=json_changes, span_id=span_id)


def _make_span(
    span_id: str,
    name: str = "test",
    parent_id: str | None = None,
) -> tuple[SpanBeginEvent, SpanEndEvent]:
    """Helper to create matching begin/end span events."""
    begin = SpanBeginEvent(id=span_id, parent_id=parent_id, name=name)
    end = SpanEndEvent(id=span_id)
    return begin, end


def test_empty_events() -> None:
    """Empty events list produces empty store."""
    events: list[Event] = []
    store = store_from_events(events)
    assert dict(store.items()) == {}


def test_single_span_with_store_event() -> None:
    """Single span containing one StoreEvent."""
    begin, end = _make_span("span1")
    store_event = _make_store_event(
        [{"op": "add", "path": "/key", "value": "value"}],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    store = store_from_events(events)

    assert store.get("key") == "value"


def test_nested_spans_uses_outer_store_event() -> None:
    """Nested spans - only outer span's StoreEvent should be used.

    The outer span's StoreEvent encompasses all changes from nested spans,
    so we should only apply the outer one to avoid double-counting.
    """
    # Create outer span
    outer_begin, outer_end = _make_span("outer")

    # Create inner span nested in outer
    inner_begin, inner_end = _make_span("inner", parent_id="outer")

    # Inner span's StoreEvent (intermediate state)
    inner_store_event = _make_store_event(
        [{"op": "add", "path": "/inner", "value": 2}],
        span_id="inner",
    )

    # Outer span's StoreEvent (final state - encompasses inner changes)
    outer_store_event = _make_store_event(
        [
            {"op": "add", "path": "/outer", "value": 1},
            {"op": "add", "path": "/inner", "value": 3},  # Overwrites inner's value
        ],
        span_id="outer",
    )

    events: list[Event] = [
        outer_begin,
        inner_begin,
        inner_store_event,
        inner_end,
        outer_store_event,
        outer_end,
    ]

    store = store_from_events(events)

    # Should have outer=1 and inner=3 (from outer's event, not inner's event)
    assert store.get("outer") == 1
    assert store.get("inner") == 3


def test_root_level_store_event_not_in_span() -> None:
    """StoreEvent at root level (not inside any span) is applied."""
    store_event = _make_store_event(
        [{"op": "add", "path": "/root_key", "value": "root_value"}],
        span_id=None,
    )

    events: list[Event] = [store_event]
    store = store_from_events(events)

    assert store.get("root_key") == "root_value"


def test_multiple_root_spans() -> None:
    """Multiple independent root-level spans are all processed."""
    begin1, end1 = _make_span("span1")
    begin2, end2 = _make_span("span2")

    store_event1 = _make_store_event(
        [{"op": "add", "path": "/key1", "value": "value1"}],
        span_id="span1",
    )
    store_event2 = _make_store_event(
        [{"op": "add", "path": "/key2", "value": "value2"}],
        span_id="span2",
    )

    events: list[Event] = [begin1, store_event1, end1, begin2, store_event2, end2]
    store = store_from_events(events)

    assert store.get("key1") == "value1"
    assert store.get("key2") == "value2"


def test_replace_operation() -> None:
    """Replace operation works correctly."""
    begin, end = _make_span("span1")

    # First add, then replace
    store_event = _make_store_event(
        [
            {"op": "add", "path": "/key", "value": "initial"},
            {"op": "replace", "path": "/key", "value": "replaced"},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    store = store_from_events(events)

    assert store.get("key") == "replaced"


def test_remove_operation() -> None:
    """Remove operation works correctly."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/to_remove", "value": "temp"},
            {"op": "add", "path": "/to_keep", "value": "keep"},
            {"op": "remove", "path": "/to_remove"},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    store = store_from_events(events)

    assert "to_remove" not in store
    assert store.get("to_keep") == "keep"


def test_nested_path_operations() -> None:
    """Operations on nested paths work correctly."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/config", "value": {}},
            {"op": "add", "path": "/config/nested", "value": {"deep": "value"}},
            {"op": "add", "path": "/config/nested/deep2", "value": "value2"},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    store = store_from_events(events)

    config = store.get("config")
    assert config["nested"]["deep"] == "value"
    assert config["nested"]["deep2"] == "value2"


def test_array_operations() -> None:
    """Array operations (add to array index) work correctly."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/items", "value": []},
            {"op": "add", "path": "/items/0", "value": "first"},
            {"op": "add", "path": "/items/1", "value": "second"},
            {"op": "add", "path": "/items/-", "value": "last"},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    store = store_from_events(events)

    assert store.get("items") == ["first", "second", "last"]


# Tests for store_from_events_as


class SampleStoreModel(StoreModel):
    """Test StoreModel for store_from_events_as tests."""

    counter: int = 0
    message: str = ""
    items: list[str] = Field(default_factory=list)


# Nested model definitions for testing StoreModel with BaseModel children


class AgentState(BaseModel):
    """Nested BaseModel representing an agent's state."""

    messages: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    last_action: str | None = None


class MetricsData(BaseModel):
    """Nested BaseModel for tracking metrics."""

    scores: list[float] = Field(default_factory=list)
    total_tokens: int = 0
    success: bool = False


class NestedStoreModel(StoreModel):
    """StoreModel with nested BaseModel children (similar to AuditStore pattern)."""

    auditor: AgentState = Field(default_factory=AgentState)
    target: AgentState = Field(default_factory=AgentState)
    metrics: MetricsData = Field(default_factory=MetricsData)
    notes: str = ""


def test_store_from_events_as_basic() -> None:
    """Basic store_from_events_as reconstruction."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/SampleStoreModel:counter", "value": 42},
            {"op": "add", "path": "/SampleStoreModel:message", "value": "hello"},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    model = store_from_events_as(events, SampleStoreModel)

    assert model.counter == 42
    assert model.message == "hello"


def test_store_from_events_as_with_defaults() -> None:
    """Fields not in events should use defaults."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [{"op": "add", "path": "/SampleStoreModel:counter", "value": 10}],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    model = store_from_events_as(events, SampleStoreModel)

    assert model.counter == 10
    assert model.message == ""  # Default
    assert model.items == []  # Default


def test_store_from_events_as_with_instance() -> None:
    """store_from_events_as with instance namespace."""
    begin, end = _make_span("span1")

    # Keys with instance namespace: SampleStoreModel:instance1:fieldname
    store_event = _make_store_event(
        [
            {"op": "add", "path": "/SampleStoreModel:instance1:counter", "value": 100},
            {
                "op": "add",
                "path": "/SampleStoreModel:instance1:message",
                "value": "inst1",
            },
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    model = store_from_events_as(events, SampleStoreModel, instance="instance1")

    assert model.counter == 100
    assert model.message == "inst1"
    assert model.instance == "instance1"


def test_store_from_events_as_ignores_other_models() -> None:
    """store_from_events_as ignores keys for other models."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/SampleStoreModel:counter", "value": 5},
            {"op": "add", "path": "/OtherModel:counter", "value": 999},
            {"op": "add", "path": "/plain_key", "value": "ignored"},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    model = store_from_events_as(events, SampleStoreModel)

    assert model.counter == 5
    # OtherModel and plain_key should be ignored


def test_store_from_events_as_with_complex_values() -> None:
    """store_from_events_as handles complex field values."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/SampleStoreModel:items", "value": ["a", "b", "c"]},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]
    model = store_from_events_as(events, SampleStoreModel)

    assert model.items == ["a", "b", "c"]


def test_deeply_nested_spans() -> None:
    """Deeply nested spans (3+ levels) - only root span events used."""
    # Level 1 (root)
    l1_begin, l1_end = _make_span("l1")
    # Level 2
    l2_begin, l2_end = _make_span("l2", parent_id="l1")
    # Level 3
    l3_begin, l3_end = _make_span("l3", parent_id="l2")

    # Events at each level
    l3_event = _make_store_event(
        [{"op": "add", "path": "/deep", "value": 3}],
        span_id="l3",
    )
    l2_event = _make_store_event(
        [{"op": "add", "path": "/mid", "value": 2}],
        span_id="l2",
    )
    l1_event = _make_store_event(
        [
            {"op": "add", "path": "/root", "value": 1},
            {"op": "add", "path": "/mid", "value": 20},
            {"op": "add", "path": "/deep", "value": 30},
        ],
        span_id="l1",
    )

    events: list[Event] = [
        l1_begin,
        l2_begin,
        l3_begin,
        l3_event,
        l3_end,
        l2_event,
        l2_end,
        l1_event,
        l1_end,
    ]

    store = store_from_events(events)

    # Should use root (l1) values, not intermediate values
    assert store.get("root") == 1
    assert store.get("mid") == 20
    assert store.get("deep") == 30


def test_mixed_root_and_span_events() -> None:
    """Mix of root-level events and events in spans."""
    # Root level event first
    root_event = _make_store_event(
        [{"op": "add", "path": "/root_first", "value": "r1"}],
        span_id=None,
    )

    # Then a span
    begin, end = _make_span("span1")
    span_event = _make_store_event(
        [{"op": "add", "path": "/from_span", "value": "s1"}],
        span_id="span1",
    )

    # Then another root level event
    root_event2 = _make_store_event(
        [{"op": "add", "path": "/root_last", "value": "r2"}],
        span_id=None,
    )

    events: list[Event] = [root_event, begin, span_event, end, root_event2]
    store = store_from_events(events)

    assert store.get("root_first") == "r1"
    assert store.get("from_span") == "s1"
    assert store.get("root_last") == "r2"


def test_store_from_events_as_instance_isolation() -> None:
    """Requesting specific instance should not include keys from other instances."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/SampleStoreModel:counter", "value": 5},
            {"op": "add", "path": "/SampleStoreModel:instance1:counter", "value": 100},
            {"op": "add", "path": "/SampleStoreModel:instance2:counter", "value": 200},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]

    # Request instance1 - should only get instance1 keys
    model = store_from_events_as(events, SampleStoreModel, instance="instance1")
    assert model.counter == 100  # Not 5 or 200


def test_store_from_events_as_no_instance_excludes_instanced_keys() -> None:
    """Without instance, should not include keys that belong to specific instances."""
    begin, end = _make_span("span1")

    store_event = _make_store_event(
        [
            {"op": "add", "path": "/SampleStoreModel:counter", "value": 5},
            {"op": "add", "path": "/SampleStoreModel:message", "value": "hello"},
            {"op": "add", "path": "/SampleStoreModel:instance1:counter", "value": 100},
        ],
        span_id="span1",
    )

    events: list[Event] = [begin, store_event, end]

    # No instance specified - should only get non-instanced keys
    model = store_from_events_as(events, SampleStoreModel)
    assert model.counter == 5
    assert model.message == "hello"


def test_json_change_move_requires_from() -> None:
    """Move operation should raise error if from field is missing."""
    from inspect_ai._util.json import JsonChange
    from inspect_ai.util._store import _json_change_to_patch_op

    # Valid move with from field (use model_validate since 'from' is aliased)
    valid_move = JsonChange.model_validate(
        {"op": "move", "path": "/dest", "from": "/src"}
    )
    result = _json_change_to_patch_op(valid_move)
    assert result == {"op": "move", "path": "/dest", "from": "/src"}

    # Invalid move without from field
    invalid_move = JsonChange(op="move", path="/dest")
    with pytest.raises(ValueError, match="requires 'from' field"):
        _json_change_to_patch_op(invalid_move)


def test_json_change_copy_requires_from() -> None:
    """Copy operation should raise error if from field is missing."""
    from inspect_ai._util.json import JsonChange
    from inspect_ai.util._store import _json_change_to_patch_op

    # Valid copy with from field (use model_validate since 'from' is aliased)
    valid_copy = JsonChange.model_validate(
        {"op": "copy", "path": "/dest", "from": "/src"}
    )
    result = _json_change_to_patch_op(valid_copy)
    assert result == {"op": "copy", "path": "/dest", "from": "/src"}

    # Invalid copy without from field
    invalid_copy = JsonChange(op="copy", path="/dest")
    with pytest.raises(ValueError, match="requires 'from' field"):
        _json_change_to_patch_op(invalid_copy)


def test_json_change_add_includes_none_value() -> None:
    """Add operation should include value even when it's None (explicit null)."""
    from inspect_ai._util.json import JsonChange
    from inspect_ai.util._store import _json_change_to_patch_op

    change = JsonChange(op="add", path="/key", value=None)
    result = _json_change_to_patch_op(change)
    assert result == {"op": "add", "path": "/key", "value": None}


def test_json_change_remove_no_value() -> None:
    """Remove operation should not include value field."""
    from inspect_ai._util.json import JsonChange
    from inspect_ai.util._store import _json_change_to_patch_op

    change = JsonChange(op="remove", path="/key")
    result = _json_change_to_patch_op(change)
    assert result == {"op": "remove", "path": "/key"}
    assert "value" not in result


# End-to-end tests: Run eval, write log, re-hydrate store from events


def test_store_from_events_end_to_end() -> None:
    """End-to-end test: run eval with multiple solvers, re-hydrate store from events.

    Uses three solvers, each setting one value, to test that store_from_events()
    correctly collects and merges changes from multiple StoreEvent instances.
    """

    @solver
    def set_counter() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.store.set("counter", 42)
            return state

        return solve

    @solver
    def set_message() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.store.set("message", "hello world")
            return state

        return solve

    @solver
    def set_nested() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.store.set("nested", {"a": 1, "b": [1, 2, 3]})
            return state

        return solve

    task = Task(
        dataset=[Sample(input="test", target="test")],
        solver=[set_counter(), set_message(), set_nested()],
        scorer=match(),
    )

    logs = eval(task, model="mockllm/model")
    log = logs[0]
    assert log.samples is not None
    sample = log.samples[0]

    # Re-hydrate store from events
    reconstructed = store_from_events(sample.events)

    assert reconstructed.get("counter") == 42
    assert reconstructed.get("message") == "hello world"
    assert reconstructed.get("nested") == {"a": 1, "b": [1, 2, 3]}


def test_store_from_events_as_end_to_end() -> None:
    """End-to-end test: run eval with multiple solvers using StoreModel.

    Uses three solvers, each setting different StoreModel fields, to test that
    store_from_events_as() correctly collects and merges changes from multiple
    StoreEvent instances.
    """

    @solver
    def set_counter() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(SampleStoreModel)
            model.counter = 100
            return state

        return solve

    @solver
    def set_message() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(SampleStoreModel)
            model.message = "from store model"
            return state

        return solve

    @solver
    def set_items() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(SampleStoreModel)
            model.items = ["a", "b", "c"]
            return state

        return solve

    task = Task(
        dataset=[Sample(input="test", target="test")],
        solver=[set_counter(), set_message(), set_items()],
        scorer=match(),
    )

    logs = eval(task, model="mockllm/model")
    assert logs[0].samples is not None
    sample = logs[0].samples[0]

    # Re-hydrate StoreModel from events
    reconstructed = store_from_events_as(sample.events, SampleStoreModel)

    assert reconstructed.counter == 100
    assert reconstructed.message == "from store model"
    assert reconstructed.items == ["a", "b", "c"]


def test_store_from_events_as_with_instances_end_to_end() -> None:
    """End-to-end test: run eval with multiple solvers writing to different instances.

    Uses three solvers, each writing to a different StoreModel instance, to test that
    store_from_events_as() correctly collects and merges changes from multiple
    StoreEvent instances while maintaining instance isolation.
    """

    @solver
    def write_base() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            base = store_as(SampleStoreModel)
            base.counter = 1
            base.message = "base"
            return state

        return solve

    @solver
    def write_agent1() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            agent1 = store_as(SampleStoreModel, instance="agent1")
            agent1.counter = 100
            agent1.message = "first agent"
            return state

        return solve

    @solver
    def write_agent2() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            agent2 = store_as(SampleStoreModel, instance="agent2")
            agent2.counter = 200
            agent2.message = "second agent"
            return state

        return solve

    task = Task(
        dataset=[Sample(input="test", target="test")],
        solver=[write_base(), write_agent1(), write_agent2()],
        scorer=match(),
    )

    logs = eval(task, model="mockllm/model")
    assert logs[0].samples is not None
    sample = logs[0].samples[0]

    # Re-hydrate each instance separately
    base = store_from_events_as(sample.events, SampleStoreModel)
    agent1 = store_from_events_as(sample.events, SampleStoreModel, instance="agent1")
    agent2 = store_from_events_as(sample.events, SampleStoreModel, instance="agent2")

    # Verify isolation
    assert base.counter == 1
    assert base.message == "base"

    assert agent1.counter == 100
    assert agent1.message == "first agent"

    assert agent2.counter == 200
    assert agent2.message == "second agent"


def test_store_from_events_via_log_file() -> None:
    """End-to-end test: write log to disk, read it back, re-hydrate store.

    Tests all scenarios:
    - Basic Store values (using state.store.set())
    - StoreModel without instance
    - StoreModel with multiple instances
    """
    import tempfile

    from inspect_ai.log import list_eval_logs, read_eval_log

    @solver
    def comprehensive_store_writer() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # 1. Basic Store values
            state.store.set("counter", 42)
            state.store.set("message", "hello world")
            state.store.set("nested", {"a": 1, "b": [1, 2, 3]})

            # 2. StoreModel without instance
            base_model = store_as(SampleStoreModel)
            base_model.counter = 100
            base_model.message = "base model"
            base_model.items = ["x", "y", "z"]

            # 3. StoreModel with instance "agent1"
            agent1 = store_as(SampleStoreModel, instance="agent1")
            agent1.counter = 200
            agent1.message = "first agent"
            agent1.items = ["a1", "a2"]

            # 4. StoreModel with instance "agent2"
            agent2 = store_as(SampleStoreModel, instance="agent2")
            agent2.counter = 300
            agent2.message = "second agent"
            agent2.items = ["b1", "b2", "b3"]

            return state

        return solve

    task = Task(
        dataset=[Sample(input="test", target="test")],
        solver=[comprehensive_store_writer()],
        scorer=match(),
    )

    with tempfile.TemporaryDirectory() as log_dir:
        eval(task, model="mockllm/model", log_dir=log_dir)

        # Read log back from disk
        log_files = list_eval_logs(log_dir)
        assert len(log_files) == 1

        log = read_eval_log(log_files[0])
        assert log.samples is not None
        sample = log.samples[0]

        # 1. Verify basic Store reconstruction
        raw_store = store_from_events(sample.events)
        assert raw_store.get("counter") == 42
        assert raw_store.get("message") == "hello world"
        assert raw_store.get("nested") == {"a": 1, "b": [1, 2, 3]}

        # 2. Verify StoreModel without instance
        base_model = store_from_events_as(sample.events, SampleStoreModel)
        assert base_model.counter == 100
        assert base_model.message == "base model"
        assert base_model.items == ["x", "y", "z"]

        # 3. Verify StoreModel with instance "agent1"
        agent1 = store_from_events_as(
            sample.events, SampleStoreModel, instance="agent1"
        )
        assert agent1.counter == 200
        assert agent1.message == "first agent"
        assert agent1.items == ["a1", "a2"]

        # 4. Verify StoreModel with instance "agent2"
        agent2 = store_from_events_as(
            sample.events, SampleStoreModel, instance="agent2"
        )
        assert agent2.counter == 300
        assert agent2.message == "second agent"
        assert agent2.items == ["b1", "b2", "b3"]

        # 5. Verify instance isolation - each instance should have its own data
        assert base_model.counter != agent1.counter != agent2.counter
        assert base_model.message != agent1.message != agent2.message


def test_store_from_events_nested_models_end_to_end() -> None:
    """End-to-end test: StoreModel with nested BaseModel children using multiple solvers.

    Tests the pattern where a StoreModel contains nested BaseModel instances
    (similar to AuditStore with AuditorStore, TargetStore, etc.), with each solver
    populating a different nested model to test merging of StoreEvents.
    """

    @solver
    def populate_auditor() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(NestedStoreModel)
            model.auditor.messages = ["Hello", "How can I help?"]
            model.auditor.tool_calls = 3
            model.auditor.last_action = "search"
            return state

        return solve

    @solver
    def populate_target() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(NestedStoreModel)
            model.target.messages = ["Task: analyze data", "Processing..."]
            model.target.tool_calls = 5
            model.target.last_action = "compute"
            return state

        return solve

    @solver
    def populate_metrics() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(NestedStoreModel)
            model.metrics.scores = [0.85, 0.92, 0.78]
            model.metrics.total_tokens = 1500
            model.metrics.success = True
            model.notes = "Evaluation complete"
            return state

        return solve

    task = Task(
        dataset=[Sample(input="test", target="test")],
        solver=[populate_auditor(), populate_target(), populate_metrics()],
        scorer=match(),
    )

    logs = eval(task, model="mockllm/model")
    assert logs[0].samples is not None
    sample = logs[0].samples[0]

    # Re-hydrate NestedStoreModel from events
    reconstructed = store_from_events_as(sample.events, NestedStoreModel)

    # Verify nested auditor state
    assert reconstructed.auditor.messages == ["Hello", "How can I help?"]
    assert reconstructed.auditor.tool_calls == 3
    assert reconstructed.auditor.last_action == "search"

    # Verify nested target state
    assert reconstructed.target.messages == ["Task: analyze data", "Processing..."]
    assert reconstructed.target.tool_calls == 5
    assert reconstructed.target.last_action == "compute"

    # Verify nested metrics
    assert reconstructed.metrics.scores == [0.85, 0.92, 0.78]
    assert reconstructed.metrics.total_tokens == 1500
    assert reconstructed.metrics.success is True

    # Verify top-level field
    assert reconstructed.notes == "Evaluation complete"


def test_store_from_events_nested_models_via_log_file() -> None:
    """End-to-end test: nested models persisted to disk and re-hydrated.

    Writes a log with nested StoreModel to disk, reads it back,
    and verifies reconstruction of nested BaseModel children.
    """
    import tempfile

    from inspect_ai.log import list_eval_logs, read_eval_log

    @solver
    def nested_model_writer() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            model = store_as(NestedStoreModel, instance="eval1")

            # Populate nested structures
            model.auditor.messages = ["Reviewing code", "Found issue"]
            model.auditor.tool_calls = 2
            model.auditor.last_action = "review"

            model.target.messages = ["Implementing fix"]
            model.target.tool_calls = 1

            model.metrics.scores = [0.95]
            model.metrics.total_tokens = 500
            model.metrics.success = True

            model.notes = "Code review session"

            return state

        return solve

    task = Task(
        dataset=[Sample(input="test", target="test")],
        solver=[nested_model_writer()],
        scorer=match(),
    )

    with tempfile.TemporaryDirectory() as log_dir:
        eval(task, model="mockllm/model", log_dir=log_dir)

        # Read log back from disk
        log_files = list_eval_logs(log_dir)
        assert len(log_files) == 1

        log = read_eval_log(log_files[0])
        assert log.samples is not None
        sample = log.samples[0]

        # Re-hydrate from file-loaded events with instance
        reconstructed = store_from_events_as(
            sample.events, NestedStoreModel, instance="eval1"
        )

        # Verify nested structures survived serialization round-trip
        assert reconstructed.auditor.messages == ["Reviewing code", "Found issue"]
        assert reconstructed.auditor.tool_calls == 2
        assert reconstructed.auditor.last_action == "review"

        assert reconstructed.target.messages == ["Implementing fix"]
        assert reconstructed.target.tool_calls == 1
        assert reconstructed.target.last_action is None  # Default value

        assert reconstructed.metrics.scores == [0.95]
        assert reconstructed.metrics.total_tokens == 500
        assert reconstructed.metrics.success is True

        assert reconstructed.notes == "Code review session"
