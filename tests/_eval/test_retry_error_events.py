from datetime import datetime, timezone

from inspect_ai._eval.task.run import TaskLogger, _eval_retry_error
from inspect_ai.event import InfoEvent, ModelEvent
from inspect_ai.log import EvalError, Transcript
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.streaming import eval_retry_error_from_history
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import init_transcript
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

    assert bounded.events_truncated is True
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
    assert bounded.events_truncated is True

    with db.open_sample_history("sample", 1) as history:
        retry = eval_retry_error_from_history(_error(), history)

    assert retry.events is not None
    assert [event.uuid for event in retry.events] == ["model-2", "info-2"]
    assert isinstance(retry.events[0], ModelEvent)
    assert len(retry.events[0].input) == 1
    assert isinstance(retry.events[0].input[0], ChatMessageUser)
    assert retry.events[0].input[0].content == "question"
    assert retry.events[0].input_refs is None


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


class _TaskLoggerShim(TaskLogger):
    def __init__(self, buffer_db: SampleBufferDatabase) -> None:
        self._buffer_db = buffer_db
