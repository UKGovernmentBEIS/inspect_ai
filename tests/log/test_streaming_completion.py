from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._eval.task.run import log_sample
from inspect_ai.event import (
    InfoEvent,
    ModelEvent,
    Timeline,
    TimelineEvent,
    TimelineSpan,
)
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._file import read_eval_log_async
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.log._recorders.json import JSONRecorder
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput


def _model(uuid: str, content: str) -> ModelEvent:
    output = ModelOutput.from_content("mockllm/model", content)
    output.choices[0].message.id = "output-message"
    return ModelEvent(
        uuid=uuid,
        timestamp=datetime(2026, 5, 18, tzinfo=timezone.utc),
        working_start=0.0,
        model="mockllm/model",
        input=[ChatMessageUser(id="input-message", content="question")],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=output,
    )


def _long_content() -> str:
    return "long answer " * 20


def _data_uri() -> str:
    return "data:image/png;base64," + ("A" * 120)


async def test_log_sample_returns_materialized_streaming_sample(
    tmp_path,
) -> None:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    sample = _sample().model_copy(
        update={"events": [InfoEvent(uuid="resident", data={})]}
    )
    db.start_sample(sample.summary())
    db.log_events(
        [
            SampleEvent(id="sample", epoch=1, event=_model("event-1", "answer-1")),
            SampleEvent(id="sample", epoch=1, event=_model("event-2", "answer-2")),
        ]
    )
    recorder = EvalRecorder(str(tmp_path))
    spec = _eval_spec()
    logger = _TaskLoggerShim(db)
    logger.recorder = recorder
    logger.eval = spec
    logger.flush_buffer = 1
    logger.flush_pending = []
    logger._samples_completed = 0
    await recorder.log_init(spec, str(tmp_path / "streaming.eval"), clean=True)
    await recorder.log_start(spec, EvalPlan())

    materialized = await log_sample(
        sample.model_copy(update={"events": []}), logger, log_images=True
    )
    await _finish_eval(recorder, spec)

    assert [event.uuid for event in materialized.events] == ["event-1", "event-2"]
    assert all(isinstance(event, ModelEvent) for event in materialized.events)
    first_event = materialized.events[0]
    assert isinstance(first_event, ModelEvent)
    assert materialized.events_data is None
    assert first_event.input[0].content == "question"
    assert first_event.input_refs is None


async def test_log_sample_rebinds_timelines_to_materialized_events(tmp_path) -> None:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    transcript_event = _model("event-1", "answer")
    sample = _sample().model_copy(
        update={
            "events": [],
            "timelines": [
                Timeline(
                    name="main",
                    description="main timeline",
                    root=TimelineSpan(
                        id="root",
                        name="root",
                        content=[TimelineEvent(event=transcript_event)],
                    ),
                )
            ],
        }
    )
    db.start_sample(sample.summary())
    db.log_events([SampleEvent(id="sample", epoch=1, event=transcript_event)])
    recorder = EvalRecorder(str(tmp_path))
    spec = _eval_spec()
    logger = _TaskLoggerShim(db)
    logger.recorder = recorder
    logger.eval = spec
    logger.flush_buffer = 1
    logger.flush_pending = []
    logger._samples_completed = 0
    await recorder.log_init(spec, str(tmp_path / "streaming.eval"), clean=True)
    await recorder.log_start(spec, EvalPlan())

    returned = await log_sample(sample, logger, log_images=True)
    await _finish_eval(recorder, spec)

    assert returned.timelines is not None
    timeline_event = returned.timelines[0].root.content[0]
    assert isinstance(timeline_event, TimelineEvent)
    assert timeline_event.event is returned.events[0]

    logged_samples = (
        await read_eval_log_async(str(tmp_path / "streaming.eval"))
    ).samples
    assert logged_samples is not None
    assert logged_samples[0].timelines is not None
    logged_timeline_event = logged_samples[0].timelines[0].root.content[0]
    assert isinstance(logged_timeline_event, TimelineEvent)
    assert logged_timeline_event.event is logged_samples[0].events[0]


async def _finish_eval(recorder: EvalRecorder, spec: EvalSpec):
    return await recorder.log_finish(
        spec, "success", EvalStats(), EvalResults(), reductions=None
    )


async def _write_eval_with_materialized_sample(path) -> object:
    recorder = EvalRecorder(str(path.parent))
    spec = _eval_spec()
    await recorder.log_init(spec, str(path), clean=True)
    await recorder.log_start(spec, EvalPlan())

    sample = _sample().model_copy(
        update={"events": [_model("event-1", _long_content())]}
    )
    await recorder.log_sample(spec, condense_sample(sample))

    await _finish_eval(recorder, spec)
    return await read_eval_log_async(str(path))


async def _write_eval_with_streaming_sample(path) -> object:
    recorder = EvalRecorder(str(path.parent))
    spec = _eval_spec()
    await recorder.log_init(spec, str(path), clean=True)
    await recorder.log_start(spec, EvalPlan())

    db = SampleBufferDatabase(
        str(path.parent / "streaming-buffer.eval"), db_dir=path.parent
    )
    db.start_sample(_sample().summary())
    db.log_events(
        [SampleEvent(id="sample", epoch=1, event=_model("event-1", _long_content()))]
    )

    with db.open_sample_history("sample", 1) as history:
        await recorder.log_sample_streaming(spec, _sample(), history)

    await _finish_eval(recorder, spec)
    return await read_eval_log_async(str(path))


@pytest.mark.anyio
async def test_streaming_completion_eval_output_matches_materialized(tmp_path):
    materialized_path = tmp_path / "materialized.eval"
    streaming_path = tmp_path / "streaming.eval"

    materialized_log = await _write_eval_with_materialized_sample(materialized_path)
    streaming_log = await _write_eval_with_streaming_sample(streaming_path)

    assert materialized_log.samples is not None
    assert streaming_log.samples is not None
    assert materialized_log.samples[0].events == streaming_log.samples[0].events
    assert (
        materialized_log.samples[0].attachments == streaming_log.samples[0].attachments
    )


@pytest.mark.anyio
async def test_eval_recorder_log_sample_streaming_writes_sample(
    tmp_path,
) -> None:
    recorder = EvalRecorder(str(tmp_path))
    spec = _eval_spec()
    await recorder.log_init(spec, clean=True)
    await recorder.log_start(spec, EvalPlan())

    with _history(tmp_path) as history:
        await recorder.log_sample_streaming(spec, _sample(), history)

    log = await recorder.log_finish(
        spec, "success", EvalStats(), EvalResults(), reductions=None
    )
    log = await read_eval_log_async(log.location)

    assert log.samples is not None
    assert len(log.samples[0].events) == 1


def _sample() -> EvalSample:
    return EvalSample(id="sample", epoch=1, input="question", target="answer")


def _sample_with_core_attachments() -> EvalSample:
    data_uri = _data_uri()
    return EvalSample(
        id="sample",
        epoch=1,
        input=[ChatMessageUser(content=data_uri)],
        target="answer",
        messages=[ChatMessageUser(content=data_uri)],
    )


def _eval_spec() -> EvalSpec:
    return EvalSpec(
        created="2026-05-18T00:00:00+00:00",
        task="streaming_completion_test",
        model="mockllm/model",
        dataset=EvalDataset(),
        config=EvalConfig(),
    )


def _history(tmp_path):
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.start_sample(_sample().summary())
    db.log_events(
        [SampleEvent(id="sample", epoch=1, event=_model("event-1", "answer"))]
    )
    return db.open_sample_history("sample", 1)


def _buffer_db(
    tmp_path: Path, events: Sequence[ModelEvent | InfoEvent]
) -> SampleBufferDatabase:
    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.start_sample(_sample().summary())
    db.log_events([SampleEvent(id="sample", epoch=1, event=event) for event in events])
    return db


async def _start_eval_recorder(tmp_path: Path) -> tuple[EvalRecorder, EvalSpec]:
    recorder = EvalRecorder(str(tmp_path))
    spec = _eval_spec()
    await recorder.log_init(spec, str(tmp_path / "streaming.eval"), clean=True)
    await recorder.log_start(spec, EvalPlan())
    return recorder, spec


async def _log_sample_with_buffer(
    tmp_path: Path,
    sample: EvalSample,
    events: Sequence[ModelEvent | InfoEvent],
    *,
    log_images: bool,
) -> tuple[EvalSample, EvalSample]:
    db = _buffer_db(tmp_path, events)
    recorder, spec = await _start_eval_recorder(tmp_path)
    logger = _TaskLoggerShim(db)
    logger.recorder = recorder
    logger.eval = spec
    logger.flush_buffer = 1
    logger.flush_pending = []
    logger._samples_completed = 0

    returned = await log_sample(sample, logger, log_images=log_images)
    await _finish_eval(recorder, spec)

    logged_samples = (
        await read_eval_log_async(str(tmp_path / "streaming.eval"))
    ).samples
    assert logged_samples is not None
    return returned, logged_samples[0]


class _TaskLoggerShim(TaskLogger):
    def __init__(self, buffer_db: SampleBufferDatabase) -> None:
        self._buffer_db = buffer_db


@pytest.mark.anyio
async def test_log_sample_writes_streamed_buffer_events_to_eval(tmp_path) -> None:
    sample = _sample().model_copy(
        update={"events": [InfoEvent(uuid="resident", data={})]}
    )
    returned, logged = await _log_sample_with_buffer(
        tmp_path, sample, [_model("event-1", "answer")], log_images=False
    )

    assert [event.uuid for event in returned.events] == ["event-1"]
    returned_event = returned.events[0]
    assert isinstance(returned_event, ModelEvent)
    assert returned_event.input[0].content == "question"
    assert [event.uuid for event in logged.events] == ["event-1"]
    logged_event = logged.events[0]
    assert isinstance(logged_event, ModelEvent)
    assert logged_event.input[0].content == "question"


@pytest.mark.anyio
async def test_log_sample_streaming_condenses_core_sample_fields_and_merges_history_attachments(
    tmp_path,
) -> None:
    sample = _sample_with_core_attachments()
    event_content = _long_content()
    returned, logged = await _log_sample_with_buffer(
        tmp_path, sample, [_model("event-1", event_content)], log_images=True
    )

    assert returned.events_data is None
    assert event_content in returned.attachments.values()
    logged_input = logged.input[0]
    assert isinstance(logged_input, ChatMessageUser)
    assert isinstance(logged_input.content, str)
    assert logged_input.content.startswith("attachment://")
    logged_message = logged.messages[0]
    assert isinstance(logged_message, ChatMessageUser)
    assert isinstance(logged_message.content, str)
    assert logged_message.content.startswith("attachment://")
    assert event_content in logged.attachments.values()
    assert logged.events_data is None


@pytest.mark.anyio
async def test_json_recorder_log_sample_streaming_includes_history_attachments(
    tmp_path,
) -> None:
    recorder = JSONRecorder(str(tmp_path))
    spec = _eval_spec()
    await recorder.log_init(spec)
    await recorder.log_start(spec, EvalPlan())

    db = SampleBufferDatabase(str(tmp_path / "test.eval"), db_dir=tmp_path)
    db.start_sample(_sample().summary())
    long_content = _long_content()
    db.log_events(
        [
            SampleEvent(
                id="sample",
                epoch=1,
                event=_model("event-1", "answer"),
            ),
            SampleEvent(
                id="sample",
                epoch=1,
                event=InfoEvent(uuid="event-2", data={"content": long_content}),
            ),
        ]
    )

    with db.open_sample_history("sample", 1) as history:
        await recorder.log_sample_streaming(spec, _sample(), history)

    samples = recorder.data[recorder._log_file_key(spec)].data.samples
    assert samples is not None
    buffered_sample = samples[0]
    assert len(buffered_sample.events) == 2
    assert buffered_sample.events_data is None
    buffered_model_event = buffered_sample.events[0]
    assert isinstance(buffered_model_event, ModelEvent)
    assert buffered_model_event.input[0].content == "question"
    buffered_info_event = buffered_sample.events[1]
    assert isinstance(buffered_info_event, InfoEvent)
    assert isinstance(buffered_info_event.data, dict)
    assert isinstance(buffered_info_event.data["content"], str)
    assert buffered_info_event.data["content"].startswith("attachment://")
    assert long_content in buffered_sample.attachments.values()

    log = await recorder.log_finish(
        spec, "success", EvalStats(), EvalResults(), reductions=None
    )

    assert log.samples is not None
    assert len(log.samples[0].events) == 2
    logged_model_event = log.samples[0].events[0]
    assert isinstance(logged_model_event, ModelEvent)
    assert logged_model_event.input[0].content == "question"
    logged_info_event = log.samples[0].events[1]
    assert isinstance(logged_info_event, InfoEvent)
    assert isinstance(logged_info_event.data, dict)
    assert logged_info_event.data["content"] == buffered_info_event.data["content"]
    assert long_content in log.samples[0].attachments.values()
