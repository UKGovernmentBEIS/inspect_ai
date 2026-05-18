"""Tests for collapse_event_versions: dedup-by-event_id with first-insertion order."""

from datetime import datetime, timezone

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.types import EventData, SampleData
from inspect_ai.log._recover._reconstruct import (
    collapse_event_versions,
    reconstruct_eval_sample,
)
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


def _event_data(row_id: int, event_id: str, payload_marker: str) -> EventData:
    """Build an EventData with a unique marker so we can assert which row was kept."""
    return EventData(
        id=row_id,
        event_id=event_id,
        sample_id="sample-1",
        epoch=1,
        event={"event": "info", "data": payload_marker},
    )


def test_first_position_with_latest_payload_under_interleaved_updates() -> None:
    """First-insertion order is preserved with the latest payload per event_id."""
    events = [
        _event_data(1, "uuid-a", "a-initial"),
        _event_data(2, "uuid-b", "b"),
        _event_data(3, "uuid-a", "a-update-1"),
        _event_data(4, "uuid-c", "c"),
        _event_data(5, "uuid-a", "a-final"),
        _event_data(6, "uuid-b", "b-final"),
    ]
    result = collapse_event_versions(events)
    assert [e.event_id for e in result] == ["uuid-a", "uuid-b", "uuid-c"]
    assert [e.event["data"] for e in result] == ["a-final", "b-final", "c"]


def test_falsy_event_id_rows_remain_unique() -> None:
    """Rows without an event_id are preserved as unique logical events."""
    events = [
        _event_data(1, "uuid-a", "a"),
        _event_data(2, "", "no-id-1"),
        _event_data(3, "uuid-a", "a-updated"),
        _event_data(4, "", "no-id-2"),
    ]
    result = collapse_event_versions(events)
    assert [e.event["data"] for e in result] == ["a-updated", "no-id-1", "no-id-2"]


def _make_model_event(
    content: str,
    *,
    pending: bool | None,
    call: ModelCall | None = None,
) -> ModelEvent:
    """Build a ModelEvent for use in pending → resolved dedup tests."""
    output = (
        ModelOutput()
        if pending
        else ModelOutput.from_content(model="mockllm/model", content=content)
    )
    return ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="test input")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=output,
        pending=pending,
        call=call,
    )


def test_reconstruct_eval_sample_dedups_model_event_pending_resolved() -> None:
    """A ModelEvent's pending and resolved rows collapse to one resolved event.

    Live ModelEvents are written twice (pending row, then resolved row
    via `_event_updated()`) sharing one UUID. Recovered messages /
    output must reflect the resolved payload.
    """
    summary = EvalSampleSummary(
        id=1,
        epoch=1,
        input="test input",
        target="test target",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    shared_uuid = "uuid-model-event"
    pending_event = _make_model_event("ignored", pending=True)
    pending_event.uuid = shared_uuid

    resolved_call = ModelCall(request={"prompt": "test"}, response={"text": "done"})
    resolved_event = _make_model_event(
        "resolved response", pending=None, call=resolved_call
    )
    resolved_event.uuid = shared_uuid

    sample_data = SampleData(
        events=[
            EventData(
                id=1,
                event_id=shared_uuid,
                sample_id="1",
                epoch=1,
                event=pending_event.model_dump(mode="json"),
            ),
            EventData(
                id=2,
                event_id=shared_uuid,
                sample_id="1",
                epoch=1,
                event=resolved_event.model_dump(mode="json"),
            ),
        ],
        attachments=[],
    )

    result = reconstruct_eval_sample(summary, sample_data)

    assert len(result.events) == 1
    [model_event] = result.events
    assert isinstance(model_event, ModelEvent)
    assert model_event.pending is None
    assert model_event.call is not None
    assert model_event.output.choices[0].message.text == "resolved response"

    assert result.output.choices[0].message.text == "resolved response"
    assert len(result.messages) == 2
    assert result.messages[-1].text == "resolved response"
