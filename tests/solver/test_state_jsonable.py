from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from pydantic_core import to_jsonable_python

from inspect_ai._util.json import json_changes
from inspect_ai.event._state import StateEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import ChatMessageUser, ModelName
from inspect_ai.model._call_tools import get_tools_info
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState, state_jsonable
from inspect_ai.solver._transcript import SolverTranscript
from inspect_ai.util._store import dict_jsonable


def _make_state() -> TaskState:
    state = TaskState(
        model=ModelName("openai/gpt-4o-mini"),
        sample_id="sample-1",
        epoch=0,
        input="hello",
        messages=[ChatMessageUser(content="hi")],
        target=Target(""),
        metadata={"foo": {"bar": 1}},
    )
    state.store.set("counter", 1)
    state.store.set("config", {"a": [1, 2]})
    return state


def _state_jsonable_baseline(state: TaskState) -> dict[str, Any]:
    """Baseline snapshot matching the original state_jsonable semantics.

    Historically, state_jsonable:
      - serialised messages/metadata via to_jsonable_python
      - used store_jsonable(state.store), which deep-copied dict_jsonable(store._data)
      - then wrapped the entire state_data in another to_jsonable_python + deepcopy
    We reproduce that behaviour here explicitly so we can compare the new,
    lighter implementation against the original JSON structure.
    """

    def as_jsonable(value: Any) -> Any:
        return to_jsonable_python(value, exclude_none=True, fallback=lambda _x: None)

    state_data = dict(
        messages=as_jsonable(state.messages),
        tools=get_tools_info(state.tools),
        tool_choice=state.tool_choice,
        store=deepcopy(dict_jsonable(state.store._data)),
        output=state.output,
        completed=state.completed,
        metadata=as_jsonable(state.metadata),
    )
    jsonable = as_jsonable(state_data)
    return cast(dict[str, Any], deepcopy(jsonable))


def test_state_jsonable_independent_of_state_mutations() -> None:
    state = _make_state()

    snapshot = state_jsonable(state)

    # Mutate state after taking the snapshot
    state.store.set("counter", 10)
    state.metadata["foo"]["bar"] = 42
    state.messages[0].content = "changed"

    # Snapshot should not change
    store_snapshot = cast(dict[str, Any], snapshot["store"])
    assert store_snapshot["counter"] == 1
    assert snapshot["metadata"]["foo"]["bar"] == 1
    assert snapshot["messages"][0]["content"] == "hi"


def test_state_jsonable_can_be_mutated_without_affecting_state() -> None:
    state = _make_state()

    snapshot = state_jsonable(state)

    # Mutate snapshot deeply
    store_snapshot = cast(dict[str, Any], snapshot["store"])
    store_snapshot["counter"] = 99
    store_snapshot["config"]["a"].append(3)
    snapshot["metadata"]["foo"]["bar"] = 7
    snapshot["messages"][0]["content"] = "snap"

    # Underlying state should remain unchanged
    assert state.store.get("counter") == 1
    assert state.store.get("config") == {"a": [1, 2]}
    assert state.metadata == {"foo": {"bar": 1}}
    assert state.messages[0].content == "hi"


def test_solver_transcript_uses_state_jsonable_for_state_changes() -> None:
    """Mirror actual SolverTranscript usage of state_jsonable + json_changes."""
    before_state = _make_state()
    after_state = _make_state()

    # Mutate the "after" state in a few places
    after_state.store.set("counter", 5)
    after_state.metadata["foo"]["bar"] = 7
    after_state.messages[0].content = "changed"

    # Expected changes using the original (baseline) state_jsonable semantics
    expected_changes = json_changes(
        _state_jsonable_baseline(before_state),
        _state_jsonable_baseline(after_state),
    )

    transcript = Transcript()
    init_transcript(transcript)

    solver_t = SolverTranscript("test-solver", before_state)
    solver_t.complete(after_state)

    events = [e for e in transcript.events if isinstance(e, StateEvent)]
    if expected_changes:
        assert len(events) == 1
        assert events[0].changes == expected_changes
    else:
        assert events == []
