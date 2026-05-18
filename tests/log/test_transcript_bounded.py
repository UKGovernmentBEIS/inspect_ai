import contextvars

import pytest

from inspect_ai._util.transcript import transcript_bounded_enabled
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._transcript import Transcript, transcript
from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


def _data(events):
    return [event.data for event in events]


def test_transcript_bounded_env_escape_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INSPECT_TRANSCRIPT_BOUNDED", raising=False)
    assert transcript_bounded_enabled() is False

    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")
    assert transcript_bounded_enabled() is True

    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "false")
    assert transcript_bounded_enabled() is False


def test_transcript_context_default_is_lazy_and_isolated() -> None:
    first_context = contextvars.Context()
    second_context = contextvars.Context()

    first = first_context.run(transcript)
    second = second_context.run(transcript)

    assert first is first_context.run(transcript)
    assert second is second_context.run(transcript)
    assert first is not second


def test_bounded_transcript_assigns_keys_to_uuidless_events() -> None:
    first = InfoEvent.model_validate(
        {"event": "info", "data": "first"}, context={"deserializing": True}
    )
    second = InfoEvent.model_validate(
        {"event": "info", "data": "second"}, context={"deserializing": True}
    )
    transcript = Transcript(bounded=True, resident_tail=1)

    transcript._event(first)
    transcript._event(second)

    assert first.uuid is not None
    assert second.uuid is not None
    assert first.uuid != second.uuid
    assert _data(transcript.events) == ["second"]


def test_bounded_transcript_evicts_to_resident_tail():
    transcript = Transcript(bounded=True, resident_tail=3)

    for data in range(5):
        transcript._event(InfoEvent(data=data))

    assert transcript.event_count == 5
    assert transcript.events_truncated is True
    assert _data(transcript.events) == [2, 3, 4]
    assert _data(transcript.recent_events(2)) == [3, 4]
    assert transcript.last_event is not None
    assert transcript.last_event.data == 4


def test_events_since_last_raises_when_transcript_truncated() -> None:
    transcript = Transcript(bounded=True, resident_tail=1)
    transcript._event(InfoEvent(data="first"))
    transcript._event(InfoEvent(data="second"))

    with pytest.raises(RuntimeError, match="Full transcript history is not available"):
        transcript.events_since_last(ModelEvent)


def test_seeded_transcript_defaults_to_unbounded():
    transcript = Transcript([InfoEvent(data=1)], resident_tail=0)

    transcript._event(InfoEvent(data=2))

    assert transcript.event_count == 2
    assert transcript.events_truncated is False
    assert _data(transcript.events) == [1, 2]


def test_sample_init_event_is_pinned_in_bounded_transcript():
    transcript = Transcript(bounded=True, resident_tail=1)
    sample_init = SampleInitEvent(
        sample=Sample(input="input", id="sample"),
        state={},
    )

    transcript._event(sample_init)
    transcript._event(InfoEvent(data=1))
    transcript._event(InfoEvent(data=2))

    assert transcript.event_count == 3
    assert transcript.events_truncated is True
    assert transcript.events == [sample_init, transcript.last_event]
    assert _data(transcript.recent_events(1)) == [2]
    assert transcript.recent_events(0) == []


def test_pending_event_is_pinned_in_bounded_transcript():
    transcript = Transcript(bounded=True, resident_tail=1)
    pending = InfoEvent(data="pending", pending=True)

    transcript._event(pending)
    transcript._event(InfoEvent(data=1))
    transcript._event(InfoEvent(data=2))

    assert transcript.event_count == 3
    assert transcript.events_truncated is True
    assert transcript.events == [pending, transcript.last_event]


def test_completed_pending_event_is_evictable_on_update():
    transcript = Transcript(bounded=True, resident_tail=1)
    pending = InfoEvent(data="pending", pending=True)

    transcript._event(pending)
    transcript._event(InfoEvent(data=1))
    pending.pending = False
    transcript._event_updated(pending)

    assert transcript.event_count == 2
    assert transcript.events_truncated is True
    assert _data(transcript.events) == [1]


def test_transcript_subscribe_receives_events_and_updates() -> None:
    transcript = Transcript()
    received: list[Event] = []
    unsubscribe = transcript.subscribe(received.append)
    event = InfoEvent(data="first")

    transcript._event(event)
    event.data = "updated"
    transcript._event_updated(event)
    unsubscribe()
    transcript._event(InfoEvent(data="after"))

    assert received == [event, event]


def test_transcript_subscriber_exception_does_not_skip_processing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transcript = Transcript(bounded=True, resident_tail=0, log_model_api=True)
    received: list[Event] = []

    def bad_subscriber(event: Event) -> None:
        raise RuntimeError("subscriber failed")

    transcript.subscribe(bad_subscriber)
    transcript.subscribe(received.append)
    event = _model_event_with_call_payload("event-1", "large payload" * 100)

    with caplog.at_level("WARNING", logger="inspect_ai.log._transcript"):
        transcript._event(event)

    assert received == [event]
    assert "Transcript subscriber failed" in caplog.text
    assert event.call is not None
    messages = event.call.request["messages"]
    assert isinstance(messages, list)
    message = messages[0]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, str)
    assert content.startswith("attachment://")
    assert transcript.events == []
    assert transcript.events_truncated is True
    assert transcript.attachments == {}


def test_bounded_transcript_evicts_unreferenced_attachments() -> None:
    transcript = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    first = _model_event_with_call_payload("event-1", "first large payload" * 100)
    second = _model_event_with_call_payload("event-2", "second large payload" * 100)

    transcript._event(first)
    first_attachments = set(transcript.attachments)
    assert first_attachments

    transcript._event(second)

    assert not first_attachments.intersection(transcript.attachments)
    assert transcript.attachments


def test_bounded_transcript_update_rebuilds_attachment_refs() -> None:
    transcript = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    event = _model_event_with_call_payload("event-1", "first payload" * 100)

    transcript._event(event)
    first_attachments = set(transcript.attachments)
    event.call = ModelCall.create(
        {"messages": [{"role": "user", "content": "second payload" * 100}]}, None
    )
    transcript._event_updated(event)

    assert not first_attachments.intersection(transcript.attachments)
    assert transcript.attachments
    assert set(transcript._attachment_refcount) == set(transcript.attachments)


def test_bounded_transcript_accepts_non_json_metadata() -> None:
    transcript = Transcript(bounded=True)

    transcript._event(InfoEvent(data="ok", metadata={"x": object()}))

    assert transcript.last_event is not None
    assert isinstance(transcript.last_event, InfoEvent)
    assert transcript.last_event.data == "ok"


def test_bounded_transcript_update_of_evicted_event_does_not_retain_attachments() -> (
    None
):
    transcript = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    evicted = _model_event_with_call_payload("event-1", "evicted payload" * 100)
    resident = InfoEvent(data="resident")

    transcript._event(evicted)
    transcript._event(resident)
    assert transcript.events == [resident]

    for index in range(3):
        evicted.call = ModelCall.create(
            {"messages": [{"role": "user", "content": f"late payload {index}" * 100}]},
            None,
        )
        transcript._event_updated(evicted)

    assert transcript.events == [resident]
    assert evicted.call is not None
    messages = evicted.call.request["messages"]
    assert isinstance(messages, list)
    message = messages[0]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, str)
    assert not content.startswith("attachment://")
    assert transcript.attachments == {}
    assert transcript._attachment_refcount == {}
    assert transcript._event_attachment_refs == {}


def _model_event_with_call_payload(uuid: str, payload: str) -> ModelEvent:
    event = ModelEvent(
        uuid=uuid,
        model="mockllm/model",
        input=[ChatMessageUser(content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "answer"),
    )
    event.call = ModelCall.create(
        {"messages": [{"role": "user", "content": payload}]}, None
    )
    return event


def test_bounded_transcript_external_mutation_keeps_original_attachment_ref() -> None:
    transcript = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    first = _model_event_with_call_payload("event-1", "first payload" * 100)
    second = InfoEvent(data="second")

    transcript._event(first)
    first_attachments = dict(transcript.attachments)
    assert first_attachments

    first.call = ModelCall.create(
        {"messages": [{"role": "user", "content": "mutated payload" * 100}]}, None
    )
    transcript._event(second)

    assert transcript.events == [second]
    assert not any(hash in transcript.attachments for hash in first_attachments)


def test_bounded_transcript_prunes_stale_pin_state_on_eviction() -> None:
    transcript = Transcript(bounded=True, resident_tail=1)
    transcript._pinned_event_ids.add("stale-pinned")
    transcript._pending_event_ids.add("stale-pending")

    transcript._event(InfoEvent(uuid="first", data="first"))
    transcript._event(InfoEvent(uuid="second", data="second"))

    assert _data(transcript.events) == ["second"]
    assert transcript._pinned_event_ids == set()
    assert transcript._pending_event_ids == set()
