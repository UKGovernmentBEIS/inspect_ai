import contextvars
from typing import NoReturn, Sequence
from unittest.mock import patch

import numpy as np
import pytest
from test_helpers.transcript import FakeTranscriptHistoryProvider, make_model_event

from inspect_ai._util.constants import DEFAULT_LOG_MODEL_API_CALLS
from inspect_ai.dataset._dataset import Sample
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.log._condense import (
    WalkContext,
    attachment_refs_from_object,
    events_attachment_fn,
    walk_model_call,
)
from inspect_ai.log._transcript import (
    Transcript,
    transcript,
    transcript_bounded_enabled,
)
from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput

ATTACHABLE = "x" * 150  # > events_attachment_fn's 100-char attachment threshold


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


def test_extend_restored_events_notifies_subscribers() -> None:
    restored = InfoEvent(uuid="restored", data="committed")
    transcript = Transcript(bounded=False)
    subscriber_events: list[Event] = []
    transcript._subscribe(subscriber_events.append)

    transcript._extend_restored_events(
        [restored],
        {},
        notify_subscribers=True,
    )

    assert transcript.history.resident_events == [restored]
    assert subscriber_events == [restored]


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


def test_shared_attachment_survives_eviction_of_one_referencing_event() -> None:
    """Eviction of one referencing event must not strip a shared attachment.

    Prefix reuse makes refcounts exceed 1; content still needed by
    other resident events must survive.
    """
    tr = Transcript(bounded=True, resident_tail=2, log_model_api=True)
    payload = "shared payload content " * 10
    for i in range(4):
        tr._event(_model_event_with_call_payload(f"event-{i}", payload))
    for event in tr._events:
        assert not attachment_refs_from_object(event) - set(tr.attachments)


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


class _LimitCapturingProvider(FakeTranscriptHistoryProvider):
    """Records `events_from` calls so tests can assert the limit rides down."""

    def __init__(self, events: Sequence[Event]) -> None:
        super().__init__(events)
        self.events_from_calls: list[tuple[int, int | None]] = []

    def events_from(self, start: int, limit: int | None = None) -> Sequence[Event]:
        self.events_from_calls.append((start, limit))
        return super().events_from(start, limit)


def test_history_events_from_serves_resident_window_without_provider() -> None:
    transcript = Transcript(bounded=True, resident_tail=3)
    for data in range(5):
        transcript._event(InfoEvent(data=data))

    # resident window is [2, 3, 4]; start inside it slices memory
    assert _data(transcript.history.events_from(3)) == [3, 4]
    assert _data(transcript.history.events_from(3, limit=1)) == [3]
    assert _data(transcript.history.events_from(3, limit=100)) == [3, 4]  # clamps
    assert transcript.history.events_from(5) == []  # at/past the end


def test_history_events_from_uses_provider_below_resident_window() -> None:
    full_history: list[Event] = [InfoEvent(data=data) for data in range(5)]
    provider = _LimitCapturingProvider(full_history)
    transcript = Transcript(bounded=True, resident_tail=2, history_provider=provider)
    for event in full_history:
        transcript._event(event)

    assert _data(transcript.history.events_from(0)) == [0, 1, 2, 3, 4]
    assert _data(transcript.history.events_from(1, limit=2)) == [1, 2]
    # the limit reaches the provider (page-sized reads, not python-side
    # truncation of a full materialization)
    assert provider.events_from_calls == [(0, None), (1, 2)]


def test_history_events_from_raises_when_history_unavailable() -> None:
    transcript = Transcript(bounded=True, resident_tail=2)
    for data in range(5):
        transcript._event(InfoEvent(data=data))

    with pytest.raises(RuntimeError, match="Full transcript history is not available"):
        transcript.history.events_from(0)
    # ...but reads within the resident window still work
    assert _data(transcript.history.events_from(3)) == [3, 4]


def test_history_events_from_unbounded_transcript() -> None:
    transcript = Transcript()
    for data in range(3):
        transcript._event(InfoEvent(data=data))

    assert _data(transcript.history.events_from(0)) == [0, 1, 2]
    assert _data(transcript.history.events_from(1, limit=100)) == [1, 2]  # clamps
    assert _data(transcript.history.events_from(-5, limit=2)) == [0, 1]  # clamps


def test_history_events_from_with_pinned_event_does_not_misalign() -> None:
    """Pinned events break the resident-suffix assumption (regression).

    A pinned SampleInitEvent survives eviction at its insertion position, so
    resident events are ['init', 7, 8, 9] for a 10-event history — not a
    contiguous suffix. Suffix arithmetic mapped logical offset 6 onto the
    pinned event, returning ['init', 7, 8] instead of [6, 7, 8]: a duplicated
    pin and a silently skipped event. Reads outside the trailing
    resident-tail window must go to the provider instead.
    """
    full_history: list[Event] = [
        SampleInitEvent(sample=Sample(input="input", id="sample"), state={}),
        *(InfoEvent(data=data) for data in range(1, 10)),
    ]
    provider = _LimitCapturingProvider(full_history)
    transcript = Transcript(bounded=True, resident_tail=3, history_provider=provider)
    for event in full_history:
        transcript._event(event)

    # sanity: the pin sits ahead of the resident tail (non-contiguous resident)
    resident = transcript.history.resident_events
    assert isinstance(resident[0], SampleInitEvent)
    assert _data(resident[1:]) == [7, 8, 9]
    assert transcript.history.event_count == 10

    # the regression: offset 6 is below the trailing window → provider
    assert _data(transcript.history.events_from(6, limit=3)) == [6, 7, 8]
    assert provider.events_from_calls == [(6, 3)]

    # the trailing resident-tail window is still a memory fast path
    provider.events_from_calls.clear()
    assert _data(transcript.history.events_from(7)) == [7, 8, 9]
    assert provider.events_from_calls == []


def test_history_events_from_with_pinned_event_and_no_provider_raises() -> None:
    transcript = Transcript(bounded=True, resident_tail=3)
    transcript._event(SampleInitEvent(sample=Sample(input="input", id="s"), state={}))
    for data in range(1, 10):
        transcript._event(InfoEvent(data=data))

    # below the trailing window: unrecoverable → error, never a misaligned page
    with pytest.raises(RuntimeError, match="Full transcript history is not available"):
        transcript.history.events_from(6)
    # the trailing window itself is fine
    assert _data(transcript.history.events_from(7)) == [7, 8, 9]


def test_bounded_transcript_prunes_message_refs_cache_on_eviction() -> None:
    tr = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    shared = ChatMessageUser(content="shared question")
    first = _model_event_with_call_payload("event-1", "first payload" * 100)
    first.input = [shared]
    second = _model_event_with_call_payload("event-2", "second payload" * 100)

    tr._event(first)
    assert shared.id is not None
    assert shared.id in tr._message_refs_cache

    tr._event(second)  # resident_tail=1 evicts event-1

    assert shared.id not in tr._message_refs_cache
    assert shared.id not in tr._message_refs_counter.counts


def test_restored_events_populate_memo_and_prune_on_eviction() -> None:
    """Resume shape end-to-end.

    Condensed restored events enter via _extend_restored_events, their
    refs resolve, and eviction releases them.
    """
    tr = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    condensed = ChatMessageUser(content="attachment://restored-ref")
    restored = make_model_event([condensed], uuid="restored-1")
    tr._extend_restored_events([restored], {"restored-ref": "restored content"})
    assert condensed.id in tr._message_refs_cache
    assert tr.attachments.get("restored-ref") == "restored content"
    tr._event(InfoEvent(uuid="filler-1", data="x"))
    tr._event(InfoEvent(uuid="filler-2", data="y"))  # evicts restored-1
    assert condensed.id not in tr._message_refs_cache


def test_message_refs_cache_distinguishes_same_id_variants() -> None:
    # resume shape: agent-state message (raw, no refs) and restored-event
    # message (condensed, refs) legitimately share one msg.id
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    raw = ChatMessageUser(content="long raw content " * 20)
    condensed = raw.model_copy(update={"content": "attachment://abc123"})
    assert raw.id == condensed.id

    ev_condensed = _model_event_with_call_payload("event-1", ATTACHABLE)
    ev_condensed.input = [condensed]
    ev_raw = _model_event_with_call_payload("event-2", ATTACHABLE)
    ev_raw.input = [raw]
    tr._event(ev_condensed)
    tr._event(ev_raw)

    assert raw.id is not None
    bucket = tr._message_refs_cache[raw.id]
    assert len(bucket) == 2
    refsets = {cached_refs for _, cached_refs in bucket}
    assert frozenset() in refsets
    assert frozenset({"abc123"}) in refsets
    # and the condensed variant's ref was refcounted
    assert tr._attachment_refs_counter.counts.get("abc123", 0) >= 1


def test_message_refs_cache_does_not_grow_for_equal_clones() -> None:
    # resolve_tool_model_input model_copies every message per generate; an
    # ==-equal clone must reuse the cached entry, not append a new one
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    original = ChatMessageUser(content="question")
    e1 = _model_event_with_call_payload("event-1", ATTACHABLE)
    e1.input = [original]
    tr._event(e1)

    clone = original.model_copy()
    assert clone is not original
    e2 = _model_event_with_call_payload("event-2", ATTACHABLE)
    e2.input = [clone]
    tr._event(e2)

    assert original.id is not None
    assert len(tr._message_refs_cache[original.id]) == 1


class _NonBoolEq:
    """Metadata value whose `__eq__` result isn't bool-coercible.

    Covers the non-ValueError half of the family (torch raises RuntimeError
    where numpy and pandas raise ValueError), so the guard can't be narrowed
    to `except ValueError` without this failing.
    """

    def __eq__(self, other: object) -> "_NonBoolEq":  # type: ignore[override]
        return self

    def __bool__(self) -> bool:
        raise RuntimeError("truth value is ambiguous")

    def __hash__(self) -> int:
        return 0


@pytest.mark.parametrize("value", [np.array([1, 2, 3]), _NonBoolEq()])
def test_message_refs_memo_tolerates_incomparable_metadata(value: object) -> None:
    # a deep-copying solver/agent yields a clone sharing the id but not the
    # metadata objects, so the memo's == arm actually runs
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    msg = ChatMessageUser(content="attachment://deadbeef", metadata={"v": value})
    tr._event(make_model_event([msg], uuid="event-1"))
    tr._event(make_model_event([msg.model_copy(deep=True)], uuid="event-2"))

    # both events' refs counted (the crash aborted _set_attachment_refs after
    # _events.append, leaving the second event's refs uncounted)
    assert tr._attachment_refs_counter.counts["deadbeef"] == 2


def test_message_refs_cache_bucket_is_bounded() -> None:
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    base = ChatMessageUser(content="variant 0 " * 20)
    assert base.id is not None
    event = _model_event_with_call_payload("event-1", ATTACHABLE)
    event.input = [base]
    tr._event(event)
    for i in range(1, 10):
        # id-preserving content rewrite (third-party pattern)
        event.input = [base.model_copy(update={"content": f"variant {i} " * 20})]
        tr._event_updated(event)
    from inspect_ai.log._transcript import _MESSAGE_REFS_BUCKET_LIMIT

    assert len(tr._message_refs_cache[base.id]) <= _MESSAGE_REFS_BUCKET_LIMIT


def test_message_refs_cache_staleness_on_in_place_mutation_is_accepted() -> None:
    """In-place content mutation without an id refresh returns stale refs.

    By design (identity hit), and safe by direction rather than id
    discipline: refs are minted only inside walk_chat_message, which copies,
    so a live message never gains one. The reachable case is a ref the
    mutation dropped staying counted — over-retention, never loss.
    """
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    msg = ChatMessageUser(content="original content " * 10)
    event = _model_event_with_call_payload("event-1", ATTACHABLE)
    event.input = [msg]
    tr._event(event)
    msg.content = "attachment://ghost"  # in-place, id unchanged
    tr._event_updated(event)
    assert (
        "ghost" not in tr._attachment_refs_counter.counts
    )  # stale memo: ref not counted


def test_event_message_ids_shrink_on_update() -> None:
    """An event whose input loses a message must release that id's refcount."""
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    keep = ChatMessageUser(content="keep")
    drop = ChatMessageUser(content="drop")
    event = _model_event_with_call_payload("event-1", ATTACHABLE)
    event.input = [keep, drop]
    tr._event(event)
    assert drop.id in tr._message_refs_counter.counts
    event.input = [keep]
    tr._event_updated(event)
    assert drop.id not in tr._message_refs_counter.counts
    assert drop.id not in tr._message_refs_cache


def test_message_refs_memo_bypassed_for_id_none() -> None:
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    msg = ChatMessageUser(content="no id here")
    msg.id = None
    event = _model_event_with_call_payload("event-1", ATTACHABLE)
    event.input = [msg]
    tr._event(event)
    assert tr._message_refs_cache == {} or None not in tr._message_refs_cache


def test_set_attachment_refs_does_not_model_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert the live-scan refs path never falls back to model_dump.

    The cycle-termination tests already pin the resulting behavioral
    difference end-to-end.
    """
    from inspect_ai.event._base import BaseEvent

    def raising(self: BaseEvent, *args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("must not call model_dump on the live-scan path")

    monkeypatch.setattr(BaseEvent, "model_dump", raising)

    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    msg = ChatMessageUser(content="attachment://in-msg")
    event = ModelEvent(
        model="m",
        input=[msg],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("m", "attachment://out-msg"),
        call=ModelCall.create(
            {"messages": [{"role": "user", "content": "attachment://call-req"}]},
            {"content": "attachment://call-resp"},
        ),
    )

    event_refs = tr._attachment_refs(event)
    assert event_refs.refs == {"in-msg", "out-msg", "call-req", "call-resp"}
    assert msg.id in event_refs.message_ids

    tr._set_attachment_refs(event)
    assert set(tr._attachment_refs_counter.counts) == event_refs.refs
    assert set(tr._message_refs_counter.counts) == event_refs.message_ids


def test_condense_model_call_empty_messages_does_not_poison_cache() -> None:
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    payload = "poison probe content " * 10
    tr._condense_model_call(
        ModelCall.create(
            {"model": "m", "messages": [{"role": "user", "content": payload}]}, None
        )
    )
    assert len(tr._call_walk_cache._slots) == 1
    for _ in range(10):
        tr._condense_model_call(ModelCall.create({"model": "m", "messages": []}, None))
    # empty requests must not occupy (or evict) lineage slots
    assert len(tr._call_walk_cache._slots) == 1


def _call_with_message_ids(ids: list[int]) -> ModelCall:
    return ModelCall.create(
        {
            "model": "m",
            "messages": [{"role": "user", "content": f"{ATTACHABLE} {i}"} for i in ids],
        },
        None,
    )


def test_condense_model_call_repeated_prefix_request_reuses_its_slot() -> None:
    """CallWalkCache copy of the CallPoolIndex tie-break regression."""
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    call = _call_with_message_ids

    long_a, short, long_b = [0, 1, 2, 3], [0, 1], [0, 1, 2, 9]
    tr._condense_model_call(call(long_a))
    tr._condense_model_call(call(short))  # partial: sibling slot
    tr._condense_model_call(call(long_b))  # partial: sibling slot
    for _ in range(10):
        tr._condense_model_call(call(short))

    # the short stream keeps one slot; both long lineages survive
    slots = tr._call_walk_cache._slots
    assert sorted(len(s.messages) for s in slots) == [2, 4, 4]


def test_condense_model_call_extending_request_replaces_the_lineage_it_consumes() -> (
    None
):
    """CallWalkCache copy of the same tie under newest-first scanning.

    The repeat above exits early on an exact match, so it no longer
    distinguishes ``>=`` from the fully-consumed tie-break. A request that
    extends past every candidate reaches no early exit, and ``>=`` then
    takes the older partial lineage and forks a sibling.
    """
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    call = _call_with_message_ids

    tr._condense_model_call(call([0, 1, 2, 3]))  # older, longer: partial match
    tr._condense_model_call(call([0, 1]))  # newer: consumed fully below
    tr._condense_model_call(call([0, 1, 9]))

    slots = tr._call_walk_cache._slots
    assert sorted(len(s.messages) for s in slots) == [3, 4]


def test_condense_model_call_matches_fresh_walk() -> None:
    """Differential oracle across a multi-lineage sequence.

    Divergence, interleave, shrink, and a second message key -- the cached
    walk must match a from-scratch walk at every step (accumulated state IS
    the point; not parametrized).
    """
    payload = "long payload " * 20

    def make_call(stream: str, n: int, response: bool) -> ModelCall:
        msgs = [
            {"role": "user", "content": f"{stream} {payload} {i}"} for i in range(n)
        ]
        return ModelCall.create(
            {"model": "m", "messages": msgs},
            {"id": "r", "content": payload} if response else None,
        )

    cached_tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    fresh_attachments: dict[str, str] = {}
    seq = [
        ("a", 1, False),
        ("a", 2, True),
        ("b", 1, False),
        ("b", 2, False),
        ("a", 3, True),
        ("a", 1, True),
        ("b", 3, True),
        ("c", 4, False),
    ]
    for stream, n, resp in seq:
        cached = cached_tr._condense_model_call(make_call(stream, n, resp))
        fresh = walk_model_call(
            make_call(stream, n, resp),
            events_attachment_fn(fresh_attachments),
            WalkContext(message_cache={}, only_core=False),
        )
        assert cached.model_dump() == fresh.model_dump()
    assert cached_tr.attachments == fresh_attachments


def test_condense_model_call_prefix_breaks_on_json_distinct_values() -> None:
    """_strict_eq, not ==: 0 vs False is python-equal but serializes differently."""
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    payload = "distinct value content " * 10
    tr._condense_model_call(
        ModelCall.create(
            {"model": "m", "messages": [{"content": payload, "n": 0}]}, None
        )
    )
    walked = tr._condense_model_call(
        ModelCall.create(
            {"model": "m", "messages": [{"content": payload, "n": False}]}, None
        )
    )
    messages = walked.request["messages"]
    assert isinstance(messages, list) and isinstance(messages[0], dict)
    assert messages[0]["n"] is False


def test_condense_model_call_reasserts_pruned_attachments() -> None:
    tr = Transcript(bounded=True, resident_tail=1, log_model_api=True)
    payload = "shared long prefix content " * 10
    first = _model_event_with_call_payload("event-1", payload)
    tr._event(first)
    assert len(tr.attachments) == 1
    ref = next(iter(tr.attachments))

    # unrelated event evicts event-1 -> refcount hits zero -> content pruned
    tr._event(InfoEvent(uuid="event-2", data="filler"))
    assert tr.attachments == {}

    # a later kept call re-sends the same request prefix: the cached walk
    # must re-assert the pruned content, else the resident event references
    # a missing attachment (silent content loss in the final log)
    second = _model_event_with_call_payload("event-3", payload)
    tr._event(second)
    assert ref in tr.attachments
    assert tr.attachments[ref].startswith("shared long prefix")


def test_condense_model_call_no_message_key_falls_back() -> None:
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    call = ModelCall.create({"model": "m", "prompt": ATTACHABLE}, None)
    walked = tr._condense_model_call(call)
    prompt = walked.request["prompt"]
    assert isinstance(prompt, str) and prompt.startswith("attachment://")
    assert tr._call_walk_cache._slots == []  # fallback never populates the cache


def test_condense_model_call_distinct_message_keys_use_distinct_lineages() -> None:
    """Distinct message keys must use distinct lineages.

    A Gemini-style 'contents' stream and an OpenAI-style 'messages' stream
    in one sample must not cross-match slots.
    """
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    msg = {"role": "user", "content": ATTACHABLE}
    tr._condense_model_call(
        ModelCall.create({"model": "m", "messages": [dict(msg)]}, None)
    )
    tr._condense_model_call(
        ModelCall.create({"model": "g", "contents": [dict(msg)]}, None)
    )
    assert sorted(s.key for s in tr._call_walk_cache._slots) == ["contents", "messages"]


def test_condense_model_call_snapshots_immune_to_mutation() -> None:
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    payload = "mutable content " * 10
    call = ModelCall.create(
        {"model": "m", "messages": [{"role": "user", "content": payload}]}, None
    )
    walked = tr._condense_model_call(call)

    # mutate BOTH the caller's request and the emitted walked structure
    # (playback shaping mutates already-logged requests in place)
    messages = call.request["messages"]
    assert isinstance(messages, list) and isinstance(messages[0], dict)
    messages[0]["content"] = "changed " * 30
    walked_messages = walked.request["messages"]
    assert isinstance(walked_messages, list) and isinstance(walked_messages[0], dict)
    walked_messages[0]["content"] = "vandalized"

    # a genuine re-send of the original content must still prefix-match and
    # produce the original walked output
    resend = ModelCall.create(
        {"model": "m", "messages": [{"role": "user", "content": payload}]}, None
    )
    walked2 = tr._condense_model_call(resend)
    messages2 = walked2.request["messages"]
    assert isinstance(messages2, list) and isinstance(messages2[0], dict)
    content2 = messages2[0]["content"]
    assert isinstance(content2, str) and content2.startswith("attachment://")
    assert tr.attachments[content2.removeprefix("attachment://")] == payload


def test_call_walk_cache_only_core_passthrough() -> None:
    """Pin the only_core early return.

    It leaves the call untouched, as in walk_model_call, and must not
    populate the walk cache or attachments.
    """
    tr = Transcript(bounded=True, resident_tail=10, log_model_api=True)
    call = ModelCall.create(
        {"model": "m", "messages": [{"role": "user", "content": ATTACHABLE}]}, None
    )
    walked = tr._call_walk_cache.condense(
        call, tr.attachments, WalkContext(message_cache={}, only_core=True)
    )
    assert walked is call  # untouched, by identity
    assert tr.attachments == {}  # no attachments created
    assert tr._call_walk_cache._slots == []
