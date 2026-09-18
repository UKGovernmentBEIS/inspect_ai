import contextlib
import warnings
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import anyio
import pytest
from pydantic import JsonValue
from test_helpers.task_logger import TaskLoggerShim

from inspect_ai import SampleSource, Task, TaskSource, eval
from inspect_ai._eval.task.run import create_eval_sample, log_sample
from inspect_ai._util.error import EvalError
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    Event,
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
    EvalSampleLimit,
    EvalSpec,
    EvalStats,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.history import SampleHistory
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.log._recorders.json import JSONRecorder
from inspect_ai.log._recorders.json_write import (
    DEFAULT_JSON_CHUNK_SIZE,
    write_json_object_field,
)
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ModelCall,
    ModelName,
    ModelOutput,
)
from inspect_ai.scorer import Score, Target
from inspect_ai.solver import Generate, Solver, TaskState, solver


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
    logger = _shim_logger(db, recorder, spec)
    await recorder.log_init(spec, str(tmp_path / "streaming.eval"), clean=True)
    await recorder.log_start(spec, EvalPlan())

    materialized = await log_sample(
        sample.model_copy(update={"events": []}),
        logger,
        log_images=True,
        from_memory=False,
        materialize_full_sample=True,
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
    logger = _shim_logger(db, recorder, spec)
    await recorder.log_init(spec, str(tmp_path / "streaming.eval"), clean=True)
    await recorder.log_start(spec, EvalPlan())

    returned = await log_sample(
        sample, logger, log_images=True, from_memory=False, materialize_full_sample=True
    )
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
async def test_streaming_write_evicts_buffered_prior(tmp_path) -> None:
    """A streaming re-log supersedes a buffered prior record for the same key.

    The streaming path zip-writes its member immediately; a prior record
    still in the flush buffer would otherwise be written *after* it, and the
    readers' name-based last-entry-wins rule would resolve the finished log
    to the stale prior (while metrics show the fresh outcome).
    """
    recorder, spec = await _start_eval_recorder(tmp_path)

    await recorder.log_sample(spec, _sample().model_copy(update={"target": "stale"}))
    with _history(tmp_path) as history:
        await recorder.log_sample_streaming(spec, _sample(), history)

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))

    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].target == "answer"


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


def _history(
    tmp_path: Path, name: str = "test"
) -> contextlib.AbstractContextManager[SampleHistory]:
    return _history_for(tmp_path, _sample(), name)


def _history_for(
    tmp_path: Path, sample: EvalSample, name: str
) -> contextlib.AbstractContextManager[SampleHistory]:
    db = SampleBufferDatabase(str(tmp_path / f"{name}.eval"), db_dir=tmp_path)
    db.start_sample(sample.summary())
    db.log_events(
        [
            SampleEvent(
                id=sample.id, epoch=sample.epoch, event=_model("event-1", "answer")
            )
        ]
    )
    return db.open_sample_history(sample.id, sample.epoch)


def _model_with_call(uuid: str, content: str, call_msgs: list[JsonValue]) -> ModelEvent:
    return _model(uuid, content).model_copy(
        update={"call": ModelCall(request={"messages": call_msgs}, response={})}
    )


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


def _shim_logger(
    db: SampleBufferDatabase, recorder: EvalRecorder, spec: EvalSpec
) -> TaskLoggerShim:
    logger = TaskLoggerShim(db)
    logger.recorder = recorder
    logger.eval = spec
    logger.flush_buffer = 1
    logger.flush_pending = []
    logger._samples_completed = 0
    return logger


async def _log_sample_with_buffer(
    tmp_path: Path,
    sample: EvalSample,
    events: Sequence[ModelEvent | InfoEvent],
    *,
    log_images: bool,
    materialize_full_sample: bool = True,
) -> tuple[EvalSample, EvalSample]:
    db = _buffer_db(tmp_path, events)
    recorder, spec = await _start_eval_recorder(tmp_path)
    logger = _shim_logger(db, recorder, spec)

    returned = await log_sample(
        sample,
        logger,
        log_images=log_images,
        from_memory=False,
        materialize_full_sample=materialize_full_sample,
    )
    await _finish_eval(recorder, spec)

    logged_samples = (
        await read_eval_log_async(str(tmp_path / "streaming.eval"))
    ).samples
    assert logged_samples is not None
    return returned, logged_samples[0]


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
async def test_log_sample_from_memory_writes_resident_events_without_buffer_readback(
    tmp_path,
) -> None:
    # When the full history is still resident (from_memory=True), log_sample must
    # write the in-memory events directly and NOT read them back from the buffer
    # DB. The buffer here holds a DIFFERENT event ("buffer-1"); the resident
    # event ("resident-1") is what must be logged.
    sample = _sample().model_copy(
        update={"events": [InfoEvent(uuid="resident-1", data={"k": "v"})]}
    )
    db = _buffer_db(tmp_path, [_model("buffer-1", "answer")])
    recorder, spec = await _start_eval_recorder(tmp_path)
    logger = _shim_logger(db, recorder, spec)

    returned = await log_sample(
        sample, logger, log_images=False, from_memory=True, materialize_full_sample=True
    )
    await _finish_eval(recorder, spec)

    logged_samples = (
        await read_eval_log_async(str(tmp_path / "streaming.eval"))
    ).samples
    assert logged_samples is not None
    assert [event.uuid for event in returned.events] == ["resident-1"]
    assert [event.uuid for event in logged_samples[0].events] == ["resident-1"]


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
async def test_log_sample_writes_restored_attachment_content_when_events_reduced(
    tmp_path: Path,
) -> None:
    """Preserve attachment content restored outside the buffer when omitting history."""
    attachment_hash = "restoredhash"
    restored_content = _long_content()
    restored_ref = f"attachment://{attachment_hash}"

    # Keep restored events resident to isolate attachment seeding from eviction.
    ts = Transcript(bounded=False)
    ts._extend_restored_events(
        [InfoEvent(uuid="restored", data={"content": restored_ref})],
        {attachment_hash: restored_content},
    )
    init_transcript(ts)

    eval_sample = create_eval_sample(
        start_time=None,
        sample=Sample(id="sample", input="question", target="answer"),
        state=TaskState(
            model=ModelName("mockllm/model"),
            sample_id="sample",
            epoch=1,
            input="question",
            messages=[],
            target=Target("answer"),
            output=ModelOutput.from_content("mockllm/model", "answer"),
        ),
        scores={},
        error=None,
        limit=None,
        error_retries=[],
        time_limit=None,
        include_events=False,
    )

    # Only the transcript holds content for this already-condensed reference.
    _, logged = await _log_sample_with_buffer(
        tmp_path,
        eval_sample,
        [InfoEvent(uuid="buffered", data={"content": restored_ref})],
        log_images=True,
        materialize_full_sample=False,
    )

    logged_event = logged.events[0]
    assert isinstance(logged_event, InfoEvent)
    assert isinstance(logged_event.data, dict)
    assert logged_event.data["content"] == restored_ref

    assert logged.attachments[attachment_hash] == restored_content


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


@pytest.mark.anyio
async def test_log_sample_degrades_gracefully_when_serialization_fails(
    tmp_path,
) -> None:
    # a sample whose content defeats condensation/serialization (here a store
    # value nested beyond pydantic-core's serialization depth limit) must not
    # raise out of log_sample (which would tear down the whole eval after the
    # fail_on_error decision): it is logged with content stripped and the
    # failure recorded as the sample's error
    sample = _sample().model_copy(
        update={
            "messages": [ChatMessageUser(content="hello")],
            "store": {"deep": _deep_dict(1000)},
            "scores": {"match": Score(value="C")},
        }
    )
    recorder, spec = await _start_eval_recorder(tmp_path)
    logger = _fallback_logger(recorder, spec)

    logged = await log_sample(
        sample, logger, log_images=True, from_memory=True, materialize_full_sample=True
    )
    await _finish_eval(recorder, spec)

    assert logged.store == {}
    assert logged.messages == []
    # the scores serialize on their own, so they are kept: the headline
    # results were computed from them and must agree with the sample record
    assert logged.scores == {"match": Score(value="C")}
    assert logged.error is not None
    assert logged.error.message.startswith(
        "Sample content (messages, output, events, store, metadata) was removed"
    )

    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].id == "sample"
    assert log.samples[0].store == {}
    assert log.samples[0].scores is not None
    assert log.samples[0].scores["match"].value == "C"
    assert log.samples[0].error is not None


@pytest.mark.anyio
async def test_log_sample_fallback_strips_unserializable_score_metadata(
    tmp_path,
) -> None:
    # when the scores themselves defeat serialization only their metadata (the
    # one score field of unbounded shape) is removed, so the value survives in
    # the record; a sample that already carries an error keeps it, with the
    # content removal appended so the empty record is explained in the log
    sample = _sample().model_copy(
        update={
            "messages": [ChatMessageUser(content="hello")],
            "scores": {
                "match": Score(
                    value="C", answer="C", metadata={"deep": _deep_dict(1000)}
                )
            },
            "error": EvalError(
                message="solver failed", traceback="", traceback_ansi=""
            ),
        }
    )
    recorder, spec = await _start_eval_recorder(tmp_path)
    logger = _fallback_logger(recorder, spec)

    logged = await log_sample(
        sample, logger, log_images=True, from_memory=True, materialize_full_sample=True
    )
    await _finish_eval(recorder, spec)

    assert logged.scores == {"match": Score(value="C", answer="C")}
    assert logged.error is not None
    assert logged.error.message.startswith("solver failed")
    assert "metadata, score metadata) was removed" in logged.error.message

    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].scores is not None
    assert log.samples[0].scores["match"].value == "C"
    assert log.samples[0].scores["match"].metadata is None
    assert log.samples[0].error is not None
    assert log.samples[0].error.message == logged.error.message


@pytest.mark.anyio
async def test_log_sample_fallback_drops_scores_as_last_resort(tmp_path) -> None:
    # a score that cannot be written even without its metadata (only reachable
    # by bypassing validation: every other Score field is of bounded shape) is
    # dropped altogether, and the record says so
    unwritable = Score.model_construct(value=_deep_dict(1000))
    sample = _sample().model_copy(
        update={
            "messages": [ChatMessageUser(content="hello")],
            "scores": {"match": unwritable},
        }
    )
    recorder, spec = await _start_eval_recorder(tmp_path)
    logger = _fallback_logger(recorder, spec)

    logged = await log_sample(
        sample, logger, log_images=True, from_memory=True, materialize_full_sample=True
    )
    await _finish_eval(recorder, spec)

    assert logged.scores is None
    assert logged.error is not None
    assert "score metadata, scores) was removed" in logged.error.message

    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].scores is None
    assert log.samples[0].error is not None


def _deep_dict(depth: int) -> dict[str, object]:
    deep: dict[str, object] = {"a": 1}
    for _ in range(depth):
        deep = {"a": deep}
    return deep


def _fallback_logger(recorder: EvalRecorder, spec: EvalSpec) -> TaskLoggerShim:
    logger = TaskLoggerShim(None)
    logger.recorder = recorder
    logger.eval = spec
    logger.flush_buffer = 1
    logger.flush_pending = []
    logger._samples_completed = 0
    return logger


@pytest.mark.anyio
async def test_log_sample_reraises_recorder_write_errors(tmp_path, monkeypatch) -> None:
    # only a condensation/serialization failure may trigger the stripped-content
    # fallback: a transient recorder write failure (e.g. an S3 blip) on a
    # healthy sample must propagate unchanged — writing a stripped fallback
    # record instead would silently drop the sample's content when a retry of
    # the eval would have logged it intact
    sample = _sample().model_copy(
        update={"messages": [ChatMessageUser(content="hello")]}
    )
    recorder, spec = await _start_eval_recorder(tmp_path)
    written: list[EvalSample] = []

    async def failing_log_sample(
        eval: EvalSpec, sample: EvalSample, **kwargs: object
    ) -> None:
        written.append(sample)
        raise OSError("simulated transient write failure")

    monkeypatch.setattr(recorder, "log_sample", failing_log_sample)
    logger = _fallback_logger(recorder, spec)

    with pytest.raises(OSError):
        await log_sample(
            sample,
            logger,
            log_images=True,
            from_memory=True,
            materialize_full_sample=True,
        )

    # a single write attempt, with the sample's content intact (no fallback)
    assert len(written) == 1
    assert written[0].messages


@pytest.mark.anyio
async def test_streamed_sample_entry_round_trips(tmp_path: Path) -> None:
    """Preserve both pools, attachments and summary fields across chunk boundaries."""
    n_events = DEFAULT_JSON_CHUNK_SIZE + 50
    events: list[ModelEvent | InfoEvent] = [
        _model(f"event-{i}", _long_content()) for i in range(n_events)
    ]
    call_msgs: list[JsonValue] = [{"role": "user", "content": "call-pool message"}]
    events[-1] = _model_with_call(f"event-{n_events - 1}", _long_content(), call_msgs)

    sample = _sample().model_copy(
        update={
            "scores": {"accuracy": Score(value=1.0, answer="42")},
            "error": EvalError(message="boom", traceback="tb", traceback_ansi="tb"),
            "limit": EvalSampleLimit(type="message", limit=50.0),
        }
    )

    returned, logged = await _log_sample_with_buffer(
        tmp_path, sample, events, log_images=True
    )

    assert len(logged.events) == len(returned.events) == n_events
    assert logged.events == returned.events
    assert logged.attachments == returned.attachments
    assert len(logged.attachments) > 0
    assert logged.scores == returned.scores == sample.scores
    assert logged.error == returned.error == sample.error
    assert logged.limit == returned.limit == sample.limit
    assert logged.events_data is None

    first_event = logged.events[0]
    assert isinstance(first_event, ModelEvent)
    assert first_event.input[0].content == "question"

    call_event = logged.events[-1]
    assert isinstance(call_event, ModelEvent)
    assert call_event.call is not None
    assert call_event.call.request["messages"] == call_msgs


@pytest.mark.anyio
async def test_buffer_sample_streaming_shields_cancellation_mid_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import inspect_ai.log._recorders.eval as eval_module

    recorder, spec = await _start_eval_recorder(tmp_path)
    events = [
        _model(f"event-{i}", _long_content())
        for i in range(DEFAULT_JSON_CHUNK_SIZE + 1)
    ]
    db = _buffer_db(tmp_path, events)

    async def cancel_then_delegate(*args: Any, **kwargs: Any) -> None:
        scope.cancel()
        await write_json_object_field(*args, **kwargs)

    # Cancel after events have been written, while the ZIP member is incomplete.
    with anyio.CancelScope() as scope:
        monkeypatch.setattr(
            eval_module, "write_json_object_field", cancel_then_delegate
        )
        with db.open_sample_history("sample", 1) as history:
            await recorder.log_sample_streaming(spec, _sample(), history)
        await anyio.lowlevel.checkpoint()

    assert scope.cancelled_caught
    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None
    assert len(log.samples[0].events) == len(events)


@pytest.mark.anyio
async def test_streamed_write_failure_leaves_log_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import inspect_ai.log._recorders.eval as eval_module

    recorder, spec = await _start_eval_recorder(tmp_path)
    sample_1 = _sample().model_copy(
        update={
            "id": "s1",
            "timelines": [
                Timeline(
                    name="main",
                    description="main timeline",
                    root=TimelineSpan(
                        id="root",
                        name="root",
                        content=[TimelineEvent(event=_model("event-1", "answer"))],
                    ),
                )
            ],
        }
    )
    sample_2 = sample_1.model_copy(update={"id": "s2"})
    with _history_for(tmp_path, sample_1, name="h1") as history:
        await recorder.log_sample_streaming(spec, sample_1, history)

    async def fail_write(*args: object, **kwargs: object) -> None:
        raise RuntimeError("serialization failed mid-write")

    monkeypatch.setattr(eval_module, "write_json_object_field", fail_write)
    with pytest.raises(RuntimeError, match="serialization failed mid-write"):
        with _history_for(tmp_path, sample_2, name="h2") as history:
            await recorder.log_sample_streaming(spec, sample_2, history)

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None
    by_id = {sample.id: sample for sample in log.samples}
    healthy = by_id["s1"]
    assert [event.uuid for event in healthy.events] == ["event-1"]
    assert healthy.timelines is not None
    timeline_event = healthy.timelines[0].root.content[0]
    assert isinstance(timeline_event, TimelineEvent)
    assert timeline_event.event is healthy.events[0]
    if "s2" in by_id:
        assert by_id["s2"].events == []
        assert by_id["s2"].timelines is None
        assert by_id["s2"].target == "answer"


@pytest.mark.anyio
async def test_streamed_sample_entry_relog_supersedes_with_no_warning(
    tmp_path: Path,
) -> None:
    recorder, spec = await _start_eval_recorder(tmp_path)
    zip_log = recorder.data[recorder._log_file_key(spec)]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with _history(tmp_path, name="h1") as history:
            await recorder.log_sample_streaming(
                spec, _sample().model_copy(update={"target": "stale"}), history
            )
        with _history(tmp_path, name="h2") as history:
            await recorder.log_sample_streaming(spec, _sample(), history)
        with zip_log._zip_open_write("warning-probe.json") as stream:
            # Another coroutine must still be able to warn while this entry is open.
            warnings.warn("Duplicate name: unrelated archive", UserWarning)
            stream.write(b"{}")
    assert [str(w.message) for w in caught if "Duplicate name" in str(w.message)] == [
        "Duplicate name: unrelated archive"
    ]

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].target == "answer"


@solver
def _attachment_emitting_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for i in range(4):
            transcript().info({"i": i, "content": f"{i} {_long_content()}"})
        assert transcript().history.resident_events_truncated
        return state

    return solve


@pytest.mark.parametrize("consumer", ["scanner", "task_source", "sample_feed"])
def test_finalization_consumers_receive_full_history(
    consumer: Literal["scanner", "task_source", "sample_feed"],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_hooks_registry: None,
) -> None:
    import inspect_ai._eval.task.run as run_module

    monkeypatch.setattr(run_module, "DEFAULT_RESIDENT_TAIL", 1)
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")
    observed: list[Sequence[Event]] = []
    sample = Sample(input="question", target="answer")
    task = Task(dataset=[sample], solver=[_attachment_emitting_solver()])

    async def sample_complete(sample: EvalSample) -> None:
        observed.append(sample.events)

    async def task_sample_complete(sample: EvalSample, task: Task) -> None:
        observed.append(sample.events)

    if consumer == "scanner":
        pytest.importorskip("inspect_scout")
        from inspect_scout import Result, Transcript
        from inspect_scout import scanner as scout_scanner

        @scout_scanner(events="all")
        def _record_events() -> Callable[[Transcript], Awaitable[Result]]:
            async def scan(transcript: Transcript) -> Result:
                observed.append(transcript.events)
                return Result(value="ok")

            return scan

        logs = eval(
            task,
            scanner=[_record_events()],
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
        )
    else:
        source: Task | TaskSource
        if consumer == "task_source":
            source = TaskSource.from_tasks([task], sample_complete=task_sample_complete)
        else:
            source = Task(
                dataset=SampleSource.from_samples(
                    [sample], sample_complete=sample_complete
                ),
                solver=[_attachment_emitting_solver()],
            )
        logs = eval(
            source, model="mockllm/model", log_dir=str(tmp_path), display="none"
        )

    assert logs[0].status == "success"
    assert len(observed) == 1
    assert [
        event.data["i"]
        for event in observed[0]
        if isinstance(event, InfoEvent)
        and isinstance(event.data, dict)
        and "i" in event.data
    ] == list(range(4))
