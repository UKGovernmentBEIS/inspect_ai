from datetime import datetime, timezone
from types import TracebackType
from typing import Iterator

import pytest
from pydantic import JsonValue

from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.run import _eval_retry_error, _sample_transcript_config
from inspect_ai.event import Event, InfoEvent, ModelEvent
from inspect_ai.log import EvalError, Transcript
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.history_provider import (
    BufferTranscriptHistoryProvider,
)
from inspect_ai.log._recorders.streaming import eval_retry_error_from_history
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import _transcript, init_transcript
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput


def _model(uuid: str, content: str) -> ModelEvent:
    output = ModelOutput.from_content("mockllm/model", content)
    return ModelEvent(
        uuid=uuid,
        timestamp=datetime(2026, 5, 18, tzinfo=timezone.utc),
        working_start=0.0,
        model="mockllm/model",
        input=[ChatMessageUser(content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=output,
    )


def _error() -> EvalError:
    return EvalError(message="boom", traceback="traceback", traceback_ansi="ansi")


@pytest.fixture(autouse=True)
def reset_transcript_context() -> Iterator[None]:
    token = _transcript.set(None)
    try:
        yield
    finally:
        _transcript.reset(token)


def test_transcript_events_since_last_returns_suffix_from_latest_type() -> None:
    first_info = InfoEvent(uuid="info-1", data={"note": "before"})
    first_model = _model("model-1", "first")
    second_info = InfoEvent(uuid="info-2", data={"note": "middle"})
    second_model = _model("model-2", "second")
    tail_info = InfoEvent(uuid="info-3", data={"note": "after"})
    transcript = Transcript(
        [first_info, first_model, second_info, second_model, tail_info]
    )

    assert transcript.events_since_last(ModelEvent) == [second_model, tail_info]


def test_eval_retry_error_uses_latest_resident_model_event_suffix() -> None:
    first_model = _model("model-1", "first")
    middle_info = InfoEvent(uuid="info-1", data={"note": "middle"})
    second_model = _model("model-2", "second")
    tail_info = InfoEvent(uuid="info-2", data={"note": "after"})
    init_transcript(Transcript([first_model, middle_info, second_model, tail_info]))

    retry = _eval_retry_error(_error())

    assert retry.events == [second_model, tail_info]


def test_eval_retry_error_does_not_claim_evicted_bounded_history() -> None:
    first_model = _model("model-1", "first")
    middle_info = InfoEvent(uuid="info-1", data={"note": "middle"})
    tail_info = InfoEvent(uuid="info-2", data={"note": "after"})
    bounded = Transcript(bounded=True, resident_tail=2)
    init_transcript(bounded)
    bounded._event(first_model)
    bounded._event(middle_info)
    bounded._event(tail_info)

    retry = _eval_retry_error(_error())

    assert bounded.resident_events_truncated is True
    assert retry.events == []


def test_eval_retry_error_uses_buffer_history_when_transcript_truncated(
    tmp_path,
) -> None:
    first_model = _model("model-1", "first")
    middle_info = InfoEvent(uuid="info-1", data={"note": "middle"})
    second_model = _model("model-2", "second")
    tail_info = InfoEvent(uuid="info-2", data={"note": "after"})
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events(
        [
            SampleEvent(id="sample", epoch=1, event=first_model),
            SampleEvent(id="sample", epoch=1, event=middle_info),
            SampleEvent(id="sample", epoch=1, event=second_model),
            SampleEvent(id="sample", epoch=1, event=tail_info),
        ]
    )

    bounded = Transcript(bounded=True, resident_tail=1)
    init_transcript(bounded)
    bounded._event(first_model)
    bounded._event(middle_info)
    bounded._event(second_model)
    bounded._event(tail_info)
    assert bounded.resident_events_truncated is True

    with db.open_sample_history("sample", 1) as history:
        retry = eval_retry_error_from_history(_error(), history)

    assert retry.events is not None
    assert [event.uuid for event in retry.events] == ["model-2", "info-2"]
    assert isinstance(retry.events[0], ModelEvent)
    assert len(retry.events[0].input) == 1
    assert isinstance(retry.events[0].input[0], ChatMessageUser)
    assert retry.events[0].input[0].content == "question"
    assert retry.events[0].input_refs is None


def test_bounded_transcript_events_since_last_uses_buffer_provider(tmp_path) -> None:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    first_model = ModelEvent(
        uuid="model-1",
        model="mockllm/model",
        input=[ChatMessageUser(content="first")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "first"),
    )
    middle = InfoEvent(uuid="info-1", data="middle")
    second_model = ModelEvent(
        uuid="model-2",
        model="mockllm/model",
        input=[ChatMessageUser(content="second")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "second"),
    )
    tail = InfoEvent(uuid="info-2", data="tail")
    events: list[Event] = [first_model, middle, second_model, tail]
    db.log_events([SampleEvent(id="sample", epoch=0, event=event) for event in events])

    provider = BufferTranscriptHistoryProvider(db, "sample", 0)
    transcript = Transcript(bounded=True, resident_tail=1, history_provider=provider)
    for event in events:
        transcript._event(event)

    assert transcript.resident_events_truncated is True
    assert transcript.events_since_last(ModelEvent) == [second_model, tail]


def test_buffer_provider_iter_events_streams_first_event_before_later_rows() -> None:
    first = InfoEvent(uuid="info-1", data="first")

    class RaisingHistory:
        events_data: dict[str, list[JsonValue]] = {"messages": [], "calls": []}

        def iter_events(self) -> Iterator[Event]:
            yield first
            raise AssertionError("iter_events should not materialize later rows first")

    class HistoryContext:
        def __enter__(self) -> RaisingHistory:
            return RaisingHistory()

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    class FakeBufferDb:
        def open_sample_history(self, sample_id: str, epoch: int) -> HistoryContext:
            assert sample_id == "sample"
            assert epoch == 0
            return HistoryContext()

        def sample_event_count(self, sample_id: str, epoch: int) -> int:
            return 1

    provider = BufferTranscriptHistoryProvider(FakeBufferDb(), "sample", 0)  # type: ignore[arg-type]
    events = provider.iter_events()

    assert next(events) == first
    with pytest.raises(AssertionError, match="later rows"):
        next(events)


def test_eval_retry_error_uses_provider_when_transcript_resident_tail_truncated(
    tmp_path,
) -> None:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    first_model = _model("model-1", "first")
    middle = InfoEvent(uuid="info-1", data="middle")
    second_model = _model("model-2", "second")
    tail = InfoEvent(uuid="info-2", data="tail")
    events: list[Event] = [first_model, middle, second_model, tail]
    db.log_events([SampleEvent(id="sample", epoch=0, event=event) for event in events])

    provider = BufferTranscriptHistoryProvider(db, "sample", 0)
    transcript = Transcript(bounded=True, resident_tail=1, history_provider=provider)
    init_transcript(transcript)
    for event in events:
        transcript._event(event)

    retry = _eval_retry_error(_error())

    assert transcript.resident_events_truncated is True
    assert transcript.full_history_available is True
    assert retry.events is not None
    assert [event.uuid for event in retry.events] == ["model-2", "info-2"]


def test_eval_retry_error_preserves_epoch_zero(tmp_path) -> None:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.log_events(
        [
            SampleEvent(id="sample", epoch=0, event=_model("model-0", "zero")),
            SampleEvent(id="sample", epoch=1, event=_model("model-1", "one")),
        ]
    )
    logger = _TaskLoggerShim(db)

    retry = _eval_retry_error(_error(), logger, "sample", 0)

    assert retry.events is not None
    assert [event.uuid for event in retry.events] == ["model-0"]


def test_eval_retry_error_requires_epoch_for_buffer_history(tmp_path) -> None:
    logger = _TaskLoggerShim(
        SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    )

    with pytest.raises(
        ValueError, match="epoch is required when reading retry events from buffer DB"
    ):
        _eval_retry_error(_error(), logger, "sample")


def test_sample_transcript_config_requires_buffer_for_bounded_mode(
    monkeypatch,
) -> None:
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")

    bounded, history_provider = _sample_transcript_config(
        logger=_TaskLoggerShim(buffer_db=None), sample_id="sample", epoch=0
    )

    assert bounded is False
    assert history_provider is None


def test_sample_transcript_config_defaults_to_unbounded_with_buffer(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("INSPECT_TRANSCRIPT_BOUNDED", raising=False)
    logger = _TaskLoggerShim(
        SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    )

    bounded, history_provider = _sample_transcript_config(
        logger=logger, sample_id="sample", epoch=0
    )

    assert bounded is False
    assert history_provider is not None


class _TaskLoggerShim(TaskLogger):
    def __init__(self, buffer_db: SampleBufferDatabase | None) -> None:
        self._buffer_db = buffer_db
