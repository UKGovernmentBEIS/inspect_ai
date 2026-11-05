"""Timing fields must be present in the ModelEvent snapshot subscribers see.

Subscribers (e.g. the sample buffer, which is what `inspect view` reads while
an eval is running) serialize the event at notification time. `completed` /
`working_time` are set after `_generate()` returns, so without a subsequent
`_event_updated()` the persisted snapshot has them null.
"""

from typing import Any

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import ModelOutput, get_model


def _snapshots() -> tuple[list[dict[str, Any]], Any]:
    """Subscribe to the transcript, serializing each ModelEvent as it arrives."""
    snapshots: list[dict[str, Any]] = []

    def on_event(event: Event) -> None:
        if isinstance(event, ModelEvent):
            snapshots.append(event.model_dump())

    return snapshots, transcript()._subscribe(on_event)


async def test_model_event_snapshot_has_completed_and_working_time() -> None:
    init_transcript(Transcript())
    snapshots, unsubscribe = _snapshots()
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", "hi")],
        )
        await model.generate("hello")
    finally:
        unsubscribe()

    assert snapshots, "expected at least one ModelEvent to reach the subscriber"
    final = snapshots[-1]
    assert final["pending"] is None
    assert final["completed"] is not None
    assert final["working_time"] is not None
    assert final["timestamp"] is not None
    assert final["working_start"] is not None


async def test_model_event_snapshot_timing_matches_live_event() -> None:
    init_transcript(Transcript())
    snapshots, unsubscribe = _snapshots()
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", "hi")],
        )
        await model.generate("hello")
    finally:
        unsubscribe()

    events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert len(events) == 1
    live = events[0].model_dump()
    final = snapshots[-1]
    assert final["uuid"] == live["uuid"]
    for field in ("timestamp", "working_start", "completed", "working_time"):
        assert final[field] == live[field]
