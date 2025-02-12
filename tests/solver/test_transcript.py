from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import transcript
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
)
import asyncio
from inspect_ai.log._transcript import ToolEvent, Transcript, init_transcript


def test_sample_transcript():
    @solver
    def transcript_solver():
        async def solve(state: TaskState, generate: Generate):
            with transcript().step("info"):
                state.metadata["foo"] = "bar"
                transcript().info(str(state.sample_id))
            return state

        return solve

    task = Task(
        dataset=[
            Sample(input="Say Hello", target="Hello"),
        ],
        solver=[transcript_solver(), generate()],
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]

    # we sometimes use this for debugging our transcript assertions
    # print(
    #     json.dumps(
    #         to_jsonable_python(log.samples[0].transcript, exclude_none=True), indent=2
    #     )
    # )

    assert log.samples[0].transcript.events[1].type == "solver"
    assert log.samples[0].transcript.events[3].data == "1"
    assert log.samples[0].transcript.events[6].event == "state"


def test_tool_event_cancellation():
    """
    Test that a ToolEvent correctly handles task assignment, cancellation,
    and that the _set_result method updates its attributes as expected.
    """
    async def dummy():
        return

    # Create a new asyncio event loop for this test
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task = loop.create_task(dummy())
        # Create a ToolEvent instance with minimum required parameters.
        event = ToolEvent(id="test_id", function="dummy_func", arguments={})
        # Set the task so that the event can attempt cancellation.
        event._set_task(task)
        # Cancel the tool event and verify the cancelled flag is set.
        event._cancel()
        assert event.cancelled is True

        # Verify that the underlying asyncio task was cancelled.
        cancelled = False
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled

        # Test that _set_result correctly updates the tool event attributes.
        dummy_result = "dummy_result"
        dummy_truncated = (0, 10)
        dummy_error = None
        dummy_events = []
        event._set_result(dummy_result, dummy_truncated, dummy_error, dummy_events)
        assert event.result == dummy_result
        assert event.truncated == dummy_truncated
        assert event.error == dummy_error
        assert event.events == dummy_events
        assert event.pending is None
    finally:
        loop.close()


def test_init_transcript_function():
    """
    Test that init_transcript correctly sets the active Transcript instance.
    """
    new_transcript = Transcript(name="new_transcript")
    init_transcript(new_transcript)
    current_transcript = transcript()
    assert current_transcript.name == "new_transcript"
import asyncio
import pytest
from inspect_ai.log._transcript import (
    Transcript,
    init_transcript,
    transcript,
    track_store_changes,
)


def test_track_store_changes(monkeypatch):
    """
    Test that the track_store_changes context manager correctly records a StoreEvent
    when a change occurs in the store.
    """
    # Create a new transcript instance and set it as active.
    new_transcript = Transcript(name="store_test")
    init_transcript(new_transcript)

    # Create a dummy store dictionary.
    dummy_store = {"key": "initial"}

    # Patch the store, store_jsonable, and store_changes functions in the module.
    monkeypatch.setattr("inspect_ai.log._transcript.store", lambda: dummy_store)
    # For simplicity, let store_jsonable just return the store dictionary unchanged.
    monkeypatch.setattr("inspect_ai.log._transcript.store_jsonable", lambda s: s)
    # Define a fake store_changes: if the before and after differ, return a list showing the update.
    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_changes",
        lambda before, after: [("update", before, after)] if before != after else [],
    )

    # Use track_store_changes context manager to capture changes.
    with track_store_changes():
        # Update the dummy store so that a change is detected.
        dummy_store["key"] = "updated"

    # Retrieve the events from the current transcript.
    events = transcript().events

    # Verify that at least one StoreEvent was recorded.
    store_events = [e for e in events if e.event == "store"]
    assert store_events, "No StoreEvent recorded."
    # Verify that the last StoreEvent has the correct changes.
    expected_changes = [("update", {"key": "initial"}, {"key": "updated"})]
    assert store_events[-1].changes == expected_changes
import asyncio
import pytest
from inspect_ai.log._transcript import (
    Transcript,
    init_transcript,
    transcript,
    track_store_changes,
)


def test_track_store_changes(monkeypatch):
    """
    Test that the track_store_changes context manager correctly records a StoreEvent
    when a change occurs in the store.
    """
    # Set up a new Transcript instance as the current transcript.
    new_transcript = Transcript(name="store_test")
    init_transcript(new_transcript)

    # Create a dummy store dictionary.
    dummy_store = {"key": "initial"}

    # Patch the store, store_jsonable, and store_changes functions so that
    # we simulate updating the store.
    monkeypatch.setattr("inspect_ai.log._transcript.store", lambda: dummy_store)
    monkeypatch.setattr("inspect_ai.log._transcript.store_jsonable", lambda s: s)
    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_changes",
        lambda before, after: [("update", before, after)] if before != after else [],
    )

    # Use track_store_changes context manager to observe changes.
    with track_store_changes():
        dummy_store["key"] = "updated"

    # Retrieve the events from the current transcript.
    events = transcript().events

    # Verify that at least one StoreEvent was recorded.
    store_events = [e for e in events if e.event == "store"]
    assert store_events, "No StoreEvent recorded."

    # Verify that the last StoreEvent has the correct changes.
    expected_changes = [("update", {"key": "initial"}, {"key": "updated"})]
    assert store_events[-1].changes == expected_changes
import asyncio
import json
import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import transcript  # transcript() function from the source code
from inspect_ai.log._transcript import (
    ToolEvent,
    Transcript,
    init_transcript,
    track_store_changes,
)
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, generate, solver


def test_sample_transcript():
    """
    Test that the transcript captures events during the processing of a Sample.
    """
    @solver
    def transcript_solver():
        async def solve(state: TaskState, generate: Generate):
            with transcript().step("info"):
                state.metadata["foo"] = "bar"
                transcript().info(str(state.sample_id))
            return state
        return solve

    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        solver=[transcript_solver(), generate()],
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]

    # Uncomment the following lines to help with debugging transcript assertions:
    # print(json.dumps(
    #     to_jsonable_python(log.samples[0].transcript, exclude_none=True), indent=2
    # ))

    # Assert that the transcript events are as expected.
    assert log.samples[0].transcript.events[1].type == "solver"
    assert log.samples[0].transcript.events[3].data == "1"
    assert log.samples[0].transcript.events[6].event == "state"


def test_tool_event_cancellation():
    """
    Test that a ToolEvent correctly cancels its asynchronous task, and its _set_result method
    updates its attributes as expected.
    """
    async def dummy():
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        task = loop.create_task(dummy())
        event = ToolEvent(id="test_id", function="dummy_func", arguments={})
        event._set_task(task)
        event._cancel()
        assert event.cancelled is True

        # Verify that the underlying asyncio task is cancelled.
        cancelled = False
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled

        # Verify that _set_result correctly updates the tool event attributes.
        dummy_result = "dummy_result"
        dummy_truncated = (0, 10)
        dummy_error = None
        dummy_events = []
        event._set_result(dummy_result, dummy_truncated, dummy_error, dummy_events)
        assert event.result == dummy_result
        assert event.truncated == dummy_truncated
        assert event.error == dummy_error
        assert event.events == dummy_events
        assert event.pending is None
    finally:
        loop.close()


def test_init_transcript_function():
    """
    Test that init_transcript correctly sets the active Transcript instance.
    """
    new_transcript = Transcript(name="new_transcript")
    init_transcript(new_transcript)
    current_transcript = transcript()
    assert current_transcript.name == "new_transcript"


def test_track_store_changes(monkeypatch):
    """
    Test that the track_store_changes context manager records a StoreEvent when the store changes.
    """
    # Create a new transcript instance and set it as the active transcript.
    new_transcript = Transcript(name="store_test")
    init_transcript(new_transcript)

    # Dummy store that will be updated.
    dummy_store = {"key": "initial"}

    # Patch the store functions in the module.
    monkeypatch.setattr("inspect_ai.log._transcript.store", lambda: dummy_store)
    monkeypatch.setattr("inspect_ai.log._transcript.store_jsonable", lambda s: s)
    monkeypatch.setattr(
        "inspect_ai.log._transcript.store_changes",
        lambda before, after: [("update", before, after)] if before != after else [],
    )

    # Use the track_store_changes context to capture changes.
    with track_store_changes():
        dummy_store["key"] = "updated"

    # Retrieve the events from the current transcript.
    events = transcript().events
    store_events = [e for e in events if e.event == "store"]
    assert store_events, "No StoreEvent recorded."
    expected_changes = [("update", {"key": "initial"}, {"key": "updated"})]
    assert store_events[-1].changes == expected_changes
