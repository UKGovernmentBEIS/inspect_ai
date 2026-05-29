import contextvars
from typing import Sequence
from unittest.mock import patch

import pytest
from test_helpers.transcript import FakeTranscriptHistoryProvider

from inspect_ai._util.constants import DEFAULT_LOG_MODEL_API_CALLS
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._transcript import (
    Transcript,
    transcript,
    transcript_bounded_enabled,
)
from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput


def _model_event_with_call(model: str = "mockllm/model") -> ModelEvent:
    return ModelEvent(
        model=model,
        input=[ChatMessageUser(content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model, "answer"),
        call=ModelCall.create({"messages": [{"role": "user", "content": "q"}]}, None),
    )


class _RaisingEventCountProvider(FakeTranscriptHistoryProvider):
    @property
    def event_count(self) -> int:
        raise AssertionError("Transcript.history.event_count should be in-memory")


class _SliceOnlyProvider(FakeTranscriptHistoryProvider):
    @property
    def event_count(self) -> int:
        raise AssertionError(
            "Transcript events slice should not read history.event_count"
        )

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        raise AssertionError("Transcript positive slice should not read recent_events")


class _NoIterProvider(FakeTranscriptHistoryProvider):
    def iter_events(self):
        raise AssertionError(
            "Transcript membership should not iterate provider history"
        )

    def recent_events(self, n: int | None = None) -> Sequence[Event]:
        raise AssertionError("Transcript resident tail should not read provider")


class _CountingContainsProvider(_NoIterProvider):
    contains_calls: int = 0

    def contains_event(self, event_id: str) -> bool:
        self.contains_calls += 1
        return super().contains_event(event_id)


class _CountingIterProvider(FakeTranscriptHistoryProvider):
    iterated: int = 0

    def iter_events(self):
        for event in self._events:
            self.iterated += 1
            yield event


def _data(events):
    return [event.data for event in events]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("true", True),
        ("1", True),
        ("false", False),
        (" FALSE ", False),
        ("Off", False),
    ],
)
def test_transcript_bounded_env_escape_hatch(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    monkeypatch.delenv("INSPECT_TRANSCRIPT_BOUNDED", raising=False)
    if value is not None:
        monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", value)
    assert transcript_bounded_enabled() is expected


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


def test_bounded_transcript_evictable_queue_stays_bounded() -> None:
    transcript = Transcript(bounded=True, resident_tail=3)

    for index in range(20):
        transcript._event(InfoEvent(data=index))

    assert _data(transcript.history.resident_events) == [17, 18, 19]
    assert len(transcript._evictable_event_ids) == 3


def test_unbounded_transcript_does_not_track_evictable_queue() -> None:
    transcript = Transcript(bounded=False)

    for index in range(20):
        transcript._event(InfoEvent(data=index))

    assert len(transcript.events) == 20
    assert list(transcript._evictable_event_ids) == []


def test_bounded_transcript_keeps_exact_resident_tail_without_truncating() -> None:
    transcript = Transcript(bounded=True, resident_tail=3)

    for index in range(3):
        transcript._event(InfoEvent(data=index))

    assert transcript.history.event_count == 3
    assert transcript.history.resident_events_truncated is False
    assert _data(transcript.history.resident_events) == [0, 1, 2]
    assert _data(transcript.events) == [0, 1, 2]


def test_completed_pending_event_evicts_before_newer_events() -> None:
    transcript = Transcript(bounded=True, resident_tail=2)
    sample_init = SampleInitEvent(
        sample=Sample(input="input", id="sample"),
        state={},
    )
    pending = InfoEvent(data="pending", pending=True)

    transcript._event(sample_init)
    transcript._event(pending)
    transcript._event(InfoEvent(data=0))
    transcript._event(InfoEvent(data=1))
    transcript._event(InfoEvent(data=2))

    pending.pending = False
    transcript._event_updated(pending)

    resident_events = transcript.history.resident_events
    assert resident_events[0] is sample_init
    assert _data(resident_events[1:]) == [1, 2]


def test_transcript_history_exposes_bounded_accessors() -> None:
    events: list[Event] = [InfoEvent(data=0), InfoEvent(data=1), InfoEvent(data=2)]
    transcript = Transcript(bounded=True, resident_tail=2)

    for event in events:
        transcript._event(event)

    assert transcript.history.event_count == 3
    assert transcript.history.last_event is events[-1]
    assert transcript.history.resident_events == events[-2:]
    assert transcript.history.resident_events_truncated is True
    assert transcript.history.full_history_available is False
    assert _data(transcript.history.recent_events(2)) == [1, 2]


def test_bounded_transcript_evicts_to_resident_tail():
    transcript = Transcript(bounded=True, resident_tail=3)

    for data in range(5):
        transcript._event(InfoEvent(data=data))

    assert transcript.history.event_count == 5
    assert transcript.history.resident_events_truncated is True
    assert _data(transcript.events) == [2, 3, 4]
    assert _data(transcript.history.recent_events(2)) == [3, 4]
    assert transcript.history.recent_events(0) == []
    assert transcript.history.last_event is not None
    assert transcript.history.last_event.data == 4


def test_bounded_transcript_recent_events_all_raises_when_history_unavailable() -> None:
    transcript = Transcript(bounded=True, resident_tail=1)
    transcript._event(InfoEvent(data="first"))
    transcript._event(InfoEvent(data="second"))

    with pytest.raises(RuntimeError, match="Full transcript history is not available"):
        transcript.history.recent_events()


def test_bounded_transcript_events_uses_provider_for_full_history() -> None:
    full_history: list[Event] = [
        InfoEvent(data=0),
        InfoEvent(data=1),
        InfoEvent(data=2),
    ]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=FakeTranscriptHistoryProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert transcript.history.resident_events_truncated is True
    assert transcript.history.full_history_available is True
    assert _data(transcript.history.resident_events) == [2]
    assert _data(transcript.events) == [0, 1, 2]
    assert len(transcript.events) == 3
    assert transcript.events[-1] is transcript.history.last_event
    assert _data(transcript.events[1:]) == [1, 2]


def test_bounded_transcript_event_count_is_in_memory_with_provider() -> None:
    full_history: list[Event] = [InfoEvent(data=0), InfoEvent(data=1)]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=_RaisingEventCountProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert transcript.history.resident_events_truncated is True
    assert transcript.history.event_count == 2


def test_provider_backed_events_len_uses_in_memory_event_count() -> None:
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=_RaisingEventCountProvider([InfoEvent(data=1)]),
    )
    transcript._event(InfoEvent(data=1))
    transcript._event(InfoEvent(data=2))

    assert len(transcript.events) == 2


def test_full_history_available_distinguishes_provider_from_resident_truncation() -> (
    None
):
    provider_backed = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=FakeTranscriptHistoryProvider(
            [InfoEvent(data=0), InfoEvent(data=1)]
        ),
    )
    provider_backed._event(InfoEvent(data=0))
    provider_backed._event(InfoEvent(data=1))

    no_provider = Transcript(bounded=True, resident_tail=1)
    no_provider._event(InfoEvent(data=0))
    no_provider._event(InfoEvent(data=1))

    assert provider_backed.history.resident_events_truncated is True
    assert provider_backed.history.full_history_available is True
    assert no_provider.history.resident_events_truncated is True
    assert no_provider.history.full_history_available is False


def test_provider_backed_events_supports_score_suffix_slice() -> None:
    full_history: list[Event] = [
        InfoEvent(data=0),
        InfoEvent(data=1),
        InfoEvent(data=2),
    ]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=FakeTranscriptHistoryProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    existing_sample_events = [full_history[0]]
    suffix = transcript.events[len(existing_sample_events) :]

    assert _data(suffix) == [1, 2]


def test_provider_backed_events_suffix_slice_uses_single_provider_operation() -> None:
    full_history: list[Event] = [
        InfoEvent(data=0),
        InfoEvent(data=1),
        InfoEvent(data=2),
    ]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=_SliceOnlyProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert _data(transcript.events[1:]) == [1, 2]


def test_provider_backed_events_membership_checks_resident_events_first() -> None:
    evicted = InfoEvent(data="evicted")
    resident = InfoEvent(data="resident")
    provider = FakeTranscriptHistoryProvider([evicted, resident])
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=provider,
    )

    transcript._event(evicted)
    transcript._event(resident)

    assert resident in transcript.events
    assert evicted in transcript.events


def test_provider_backed_positive_index_streams_until_match() -> None:
    full_history: list[Event] = [
        InfoEvent(data=0),
        InfoEvent(data=1),
        InfoEvent(data=2),
    ]
    provider = _CountingIterProvider(full_history)
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=provider,
    )

    for event in full_history:
        transcript._event(event)

    event = transcript.events[1]

    assert isinstance(event, InfoEvent)
    assert event.data == 1
    assert provider.iterated == 2


def test_bounded_transcript_recent_events_uses_provider_when_resident_tail_insufficient() -> (
    None
):
    full_history: list[Event] = [
        InfoEvent(data=0),
        InfoEvent(data=1),
        InfoEvent(data=2),
    ]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=FakeTranscriptHistoryProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert _data(transcript.history.recent_events(2)) == [1, 2]
    assert transcript.history.recent_events(0) == []
    assert _data(transcript.history.recent_events()) == [0, 1, 2]


def test_provider_backed_resident_tail_shortcuts_avoid_provider() -> None:
    full_history: list[Event] = [
        InfoEvent(data=0),
        InfoEvent(data=1),
        InfoEvent(data=2),
    ]
    transcript = Transcript(
        bounded=True,
        resident_tail=2,
        history_provider=_NoIterProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert transcript.history.resident_events_truncated is True
    assert _data(transcript.history.recent_events(1)) == [2]
    assert transcript.events[-1] is full_history[-1]
    assert transcript.events[-2:] == full_history[-2:]


def test_bounded_transcript_recent_events_uses_provider_with_pinned_gap() -> None:
    sample_init = SampleInitEvent(
        sample=Sample(input="input", id="sample"),
        state={},
    )
    full_history: list[Event] = [sample_init, InfoEvent(data=1), InfoEvent(data=2)]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=FakeTranscriptHistoryProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert transcript.history.resident_events == [sample_init, full_history[-1]]
    assert _data(transcript.history.recent_events(2)) == [1, 2]


@pytest.mark.parametrize("pin_first", [False, True])
def test_bounded_transcript_events_negative_index_uses_provider_with_empty_tail(
    pin_first: bool,
) -> None:
    first: Event = (
        SampleInitEvent(sample=Sample(input="input", id="sample"), state={})
        if pin_first
        else InfoEvent(data=0)
    )
    tail = InfoEvent(data="tail")
    full_history: list[Event] = [first, tail]
    transcript = Transcript(
        bounded=True,
        resident_tail=0,
        history_provider=FakeTranscriptHistoryProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    expected_resident = [first] if pin_first else []
    assert transcript.history.resident_events == expected_resident
    assert transcript.events[-1] is tail
    if pin_first:
        assert transcript.history.last_event is first
        assert list(transcript.events)[-1] is tail


def test_bounded_transcript_membership_finds_evicted_provider_event() -> None:
    full_history: list[Event] = [InfoEvent(data=0), InfoEvent(data=1)]
    provider = _CountingContainsProvider(full_history)
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=provider,
    )

    for event in full_history:
        transcript._event(event)

    assert full_history[0] in transcript.events
    assert provider.contains_calls == 1


def test_untruncated_provider_backed_membership_does_not_scan_provider() -> None:
    event = InfoEvent(data="resident")
    missing = InfoEvent(data="missing")
    transcript = Transcript(
        bounded=True,
        resident_tail=2,
        history_provider=_NoIterProvider([event]),
    )

    transcript._event(event)

    assert missing not in transcript.events


def test_bounded_transcript_prunes_model_call_budget_on_eviction() -> None:
    transcript = Transcript(bounded=True, resident_tail=0)

    for _ in range(DEFAULT_LOG_MODEL_API_CALLS):
        evicted = _model_event_with_call()
        transcript._event(evicted)
        assert evicted.call is not None
    assert transcript.history.resident_events == []

    second = _model_event_with_call()
    transcript._event(second)
    assert second.call is not None


def test_bounded_transcript_events_since_last_uses_provider_after_eviction() -> None:
    first_model = ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="first")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "first"),
    )
    middle = InfoEvent(data="middle")
    second_model = ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="second")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "second"),
    )
    tail = InfoEvent(data="tail")
    full_history: list[Event] = [first_model, middle, second_model, tail]
    transcript = Transcript(
        bounded=True,
        resident_tail=1,
        history_provider=FakeTranscriptHistoryProvider(full_history),
    )

    for event in full_history:
        transcript._event(event)

    assert transcript.history.events_since_last(ModelEvent) == [second_model, tail]


def test_events_since_last_raises_when_transcript_truncated() -> None:
    transcript = Transcript(bounded=True, resident_tail=1)
    transcript._event(InfoEvent(data="first"))
    transcript._event(InfoEvent(data="second"))

    with pytest.raises(RuntimeError, match="Full transcript history is not available"):
        transcript.history.events_since_last(ModelEvent)


def test_seeded_transcript_defaults_to_unbounded():
    transcript = Transcript([InfoEvent(data=1)], resident_tail=0)

    transcript._event(InfoEvent(data=2))

    assert transcript.history.event_count == 2
    assert transcript.history.resident_events_truncated is False
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

    assert transcript.history.event_count == 3
    assert transcript.history.resident_events_truncated is True
    assert transcript.events == [sample_init, transcript.history.last_event]


def test_pending_event_is_pinned_in_bounded_transcript():
    transcript = Transcript(bounded=True, resident_tail=1)
    pending = InfoEvent(data="pending", pending=True)

    transcript._event(pending)
    transcript._event(InfoEvent(data=1))
    transcript._event(InfoEvent(data=2))

    assert transcript.history.event_count == 3
    assert transcript.history.resident_events_truncated is True
    assert transcript.events == [pending, transcript.history.last_event]


def test_completed_pending_event_is_evictable_on_update():
    transcript = Transcript(bounded=True, resident_tail=1)
    pending = InfoEvent(data="pending", pending=True)

    transcript._event(pending)
    transcript._event(InfoEvent(data=1))
    pending.pending = False
    transcript._event_updated(pending)

    assert transcript.history.event_count == 2
    assert transcript.history.resident_events_truncated is True
    assert _data(transcript.events) == [1]


def test_transcript_subscribe_receives_events_and_updates() -> None:
    transcript = Transcript()
    received: list[Event] = []
    unsubscribe = transcript._subscribe(received.append)
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

    transcript._subscribe(bad_subscriber)
    transcript._subscribe(received.append)
    event = _model_event_with_call_payload("event-1", "large payload" * 100)

    with patch("inspect_ai.log._transcript.logger.warning") as warning:
        transcript._event(event)

    assert received == [event]
    warning.assert_called_once()
    assert warning.call_args.args[0] == "Transcript subscriber failed"
    assert warning.call_args.kwargs["exc_info"] is True
    assert event.call is not None
    messages = event.call.request["messages"]
    assert isinstance(messages, list)
    message = messages[0]
    assert isinstance(message, dict)
    content = message["content"]
    assert isinstance(content, str)
    assert content.startswith("attachment://")
    assert transcript.events == []
    assert transcript.history.resident_events_truncated is True
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


def test_bounded_transcript_accepts_non_json_metadata() -> None:
    transcript = Transcript(bounded=True)

    transcript._event(InfoEvent(data="ok", metadata={"x": object()}))

    assert transcript.history.last_event is not None
    assert isinstance(transcript.history.last_event, InfoEvent)
    assert transcript.history.last_event.data == "ok"


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


def test_restored_events_update_bounded_bookkeeping_and_evict() -> None:
    transcript = Transcript(bounded=True, resident_tail=2)
    events = [InfoEvent(data=i) for i in range(5)]

    transcript._extend_restored_events(events, {})

    assert transcript.history.event_count == 5
    assert transcript.history.resident_events_truncated is True
    assert _data(transcript.history.resident_events) == [3, 4]
    assert _data(transcript.history.recent_events(2)) == [3, 4]


def test_restored_events_reject_duplicate_uuid() -> None:
    transcript = Transcript(bounded=True, resident_tail=10)
    first = InfoEvent(data="first", uuid="same")
    duplicate = InfoEvent(data="duplicate", uuid="same")

    transcript._extend_restored_events([first], {})

    with pytest.raises(ValueError, match="Duplicate event uuid"):
        transcript._extend_restored_events([duplicate], {})


def test_bounded_transcript_allows_duplicate_uuid_after_eviction() -> None:
    transcript = Transcript(bounded=True, resident_tail=1)
    first = InfoEvent(data="first", uuid="same")
    second = InfoEvent(data="second", uuid="other")
    duplicate = InfoEvent(data="duplicate", uuid="same")

    transcript._event(first)
    transcript._event(second)
    assert _data(transcript.history.resident_events) == ["second"]

    transcript._event(duplicate)

    assert _data(transcript.history.resident_events) == ["duplicate"]
