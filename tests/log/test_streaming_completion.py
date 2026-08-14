import contextlib
import re
import warnings
from collections.abc import Awaitable, Callable, Generator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import anyio
import pytest
from pydantic import JsonValue
from test_helpers.task_logger import TaskLoggerShim
from typing_extensions import assert_never

from inspect_ai import SampleSource, Task, TaskSource, eval
from inspect_ai._eval.task.run import create_eval_sample, log_sample
from inspect_ai._util.error import EvalError
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.event import (
    InfoEvent,
    ModelEvent,
    Timeline,
    TimelineEvent,
    TimelineSpan,
)
from inspect_ai.hooks import Hooks, hooks
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._file import read_eval_log, read_eval_log_async
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
from inspect_ai.log._recorders.eval import EvalRecorder, ZipLogFile, _sample_filename
from inspect_ai.log._recorders.json import JSONRecorder
from inspect_ai.log._recorders.json_write import (
    DEFAULT_JSON_CHUNK_SIZE,
    write_json_object_field,
)
from inspect_ai.log._recorders.streaming import materialize_streaming_sample
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
    """A ModelEvent whose ``call`` request populates the call pool.

    ``condense_model_event_with_indices`` pools ``call.request["messages"]``
    the same way it pools ``input`` — see ``_CALL_MESSAGE_KEYS`` in
    ``inspect_ai.event._pool``.
    """
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
    """Checkpoint-restored attachment content must reach the written log.

    Even on the reduced/evicted finalization path (`materialize_full_sample=False`).
    Simulates a resumed sample the way `_push_host_state`
    (`inspect_ai/util/_checkpoint/hydrate.py`) does for a real checkpoint
    resume: `Transcript._extend_restored_events` pushes a condensed event
    carrying an `attachment://<hash>` ref together with the `{hash:
    content}` mapping that resolves it. That mapping lives only in the
    transcript's own attachment store -- the realtime buffer never captured
    it, since it arrived already condensed rather than as raw content for
    the buffer's own condenser to hash and store. `create_eval_sample` must
    seed `EvalSample.attachments` from the transcript unconditionally (not
    only when `include_events` is set) so the ref still resolves once
    written, even though the buffer's own history has no content for it.

    The no-eviction setup (`bounded=False`) is deliberate: it isolates the
    one thing this code path could regress, the unconditional attachment
    seeding. Bounded eviction dropping the restored mapping itself is a
    pre-existing upstream bug tracked separately.
    """
    attachment_hash = "restoredhash"
    restored_content = _long_content()
    restored_ref = f"attachment://{attachment_hash}"

    ts = Transcript(bounded=False)
    ts._extend_restored_events(
        [InfoEvent(uuid="restored", data={"content": restored_ref})],
        {attachment_hash: restored_content},
    )
    init_transcript(ts)

    eval_sample = create_eval_sample(
        start_time=None,
        sample=Sample(id="sample", input="question", target="answer"),
        # epoch=1 matches the (id, epoch) key `_log_sample_with_buffer`'s
        # buffer starts the sample under -- `log_sample` looks up the buffer
        # history by this key.
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
        include_events=False,
    )

    # The buffer's own history carries the same ref as a short literal
    # string (as it would if the event were logged already condensed): well
    # under the buffer's condensing threshold, so its own condenser passes
    # it through untouched and never hashes/stores content for this ref.
    # The seed above is the only place the content is available.
    _returned, logged = await _log_sample_with_buffer(
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

    assert logged.attachments.get(attachment_hash) == restored_content, (
        "restored attachment content did not reach the written log: dangling ref"
    )


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
async def test_streamed_sample_entry_round_trips(tmp_path: Path) -> None:
    """The streamed zip entry reads back equal to the materialized sample.

    Covers >1 chunk of events, non-empty message and call pools, an
    attachment, a score, an error, and a limit - order-insensitive.
    """
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
async def test_streamed_sample_entry_empty_events_edge(tmp_path: Path) -> None:
    """A sample whose history has zero events still writes a valid entry."""
    recorder, spec = await _start_eval_recorder(tmp_path)

    db = SampleBufferDatabase(str(tmp_path / "empty.eval"), db_dir=tmp_path)
    db.start_sample(_sample().summary())

    with db.open_sample_history("sample", 1) as history:
        await recorder.log_sample_streaming(spec, _sample(), history)

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))

    assert log.samples is not None
    logged = log.samples[0]
    assert logged.events == []
    assert logged.attachments == {}
    assert logged.events_data is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "writer_name", ["write_json_array_field", "write_json_object_field"]
)
async def test_buffer_sample_streaming_shields_cancellation_mid_write(
    writer_name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A cancellation delivered mid-entry-write must not truncate the member.

    Deterministic stand-in for real task cancellation landing at one of the
    checkpoints inside the entry write: monkeypatches the named writer (the
    "events" array and the "attachments" object are distinct landing sites
    within the same entry) to cancel the enclosing scope, so the cancellation
    is pending at the checkpoint between chunks inside
    ``buffer_sample_streaming``'s zip-entry write. Without shielding that
    write, the checkpoint raises there and the mid-write failure repair
    supersedes the truncated member with an event-less stub, so the
    sample's events would be silently lost from the finished log.
    """
    import inspect_ai.log._recorders.eval as eval_module

    recorder, spec = await _start_eval_recorder(tmp_path)
    events = [
        _model(f"event-{i}", _long_content())
        for i in range(DEFAULT_JSON_CHUNK_SIZE + 50)
    ]
    db = _buffer_db(tmp_path, events)

    original_writer = getattr(eval_module, writer_name)
    fired = {"done": False}

    async def cancel_then_delegate(*args: Any, **kwargs: Any) -> None:
        fired["done"] = True
        # cancel() is idempotent, so no first-call guard is needed
        scope.cancel()
        await original_writer(*args, **kwargs)

    with anyio.CancelScope() as scope:
        monkeypatch.setattr(eval_module, writer_name, cancel_then_delegate)
        with db.open_sample_history("sample", 1) as history:
            await recorder.log_sample_streaming(spec, _sample(), history)
        # The shield only defers cancellation past the entry write, it must
        # not drop it: liveness is retained via the checkpoint below.
        await anyio.lowlevel.checkpoint()

    assert fired["done"], (
        f"spy never fired: buffer_sample_streaming no longer routes"
        f" through {writer_name}"
    )
    assert scope.cancelled_caught, "deferred cancellation was never delivered"

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))

    assert log.samples is not None
    assert len(log.samples[0].events) == len(events)


def _fail_second_object_field_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the second sample's streamed entry raise mid-write (one object-field write per sample)."""
    import inspect_ai.log._recorders.eval as eval_module

    calls = {"n": 0}

    async def failing_object_field(*args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("serialization failed mid-write")
        await write_json_object_field(*args, **kwargs)

    monkeypatch.setattr(eval_module, "write_json_object_field", failing_object_field)


@pytest.mark.anyio
async def test_streamed_write_failure_leaves_log_readable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An exception mid-entry-write must not poison the whole log.

    ``_zip_open_write``'s ``__exit__`` finalizes the zip member on any exit
    path, so a raise between chunks would otherwise register a truncated
    (invalid JSON) member — and ``_read_log`` parses every sample member
    eagerly, so even healthy samples become unreadable. The recorder must
    supersede the truncated member with a valid one before propagating.
    """
    recorder, spec = await _start_eval_recorder(tmp_path)
    _fail_second_object_field_write(monkeypatch)

    sample_1 = EvalSample(id="s1", epoch=1, input="question", target="answer")
    sample_2 = EvalSample(id="s2", epoch=1, input="question", target="answer")

    with _history_for(tmp_path, sample_1, name="h1") as history:
        await recorder.log_sample_streaming(spec, sample_1, history)
    with pytest.raises(RuntimeError, match="serialization failed mid-write"):
        with _history_for(tmp_path, sample_2, name="h2") as history:
            await recorder.log_sample_streaming(spec, sample_2, history)

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))

    assert log.samples is not None
    by_id = {s.id: s for s in log.samples}
    healthy = by_id["s1"]
    assert [event.uuid for event in healthy.events] == ["event-1"]
    # the failed sample is either absent or a valid event-less stub
    if "s2" in by_id:
        assert by_id["s2"].events == []
        assert by_id["s2"].target == "answer"


@pytest.mark.anyio
async def test_streamed_write_failure_stub_drops_timelines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The repair stub must not retain timelines.

    Timeline events serialize as event-UUID strings which are rebound against
    ``sample.events`` on read; the stub's events are empty, so a retained
    timeline fails validation — turning the repair stub itself into the
    poisoned member it exists to prevent.
    """
    recorder, spec = await _start_eval_recorder(tmp_path)
    _fail_second_object_field_write(monkeypatch)

    def _timeline_sample(id: str) -> EvalSample:
        return EvalSample(
            id=id,
            epoch=1,
            input="question",
            target="answer",
            timelines=[
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
        )

    sample_1 = _timeline_sample("s1")
    sample_2 = _timeline_sample("s2")

    with _history_for(tmp_path, sample_1, name="h1") as history:
        await recorder.log_sample_streaming(spec, sample_1, history)
    with pytest.raises(RuntimeError, match="serialization failed mid-write"):
        with _history_for(tmp_path, sample_2, name="h2") as history:
            await recorder.log_sample_streaming(spec, sample_2, history)

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))

    assert log.samples is not None
    by_id = {s.id: s for s in log.samples}
    # the healthy streamed member keeps its timeline, rebound to its events
    healthy = by_id["s1"]
    assert [event.uuid for event in healthy.events] == ["event-1"]
    assert healthy.timelines is not None
    healthy_timeline_event = healthy.timelines[0].root.content[0]
    assert isinstance(healthy_timeline_event, TimelineEvent)
    assert healthy_timeline_event.event is healthy.events[0]
    # the repaired stub drops timelines alongside its events/attachments
    if "s2" in by_id:
        assert by_id["s2"].events == []
        assert by_id["s2"].timelines is None


@pytest.mark.anyio
async def test_streaming_path_never_serializes_whole_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Guard: no whole-sample writestr on the streaming path."""
    written: list[str] = []
    original = ZipLogFile._zip_writestr

    def recording(self: ZipLogFile, filename: str, data: Any) -> None:
        written.append(filename)
        return original(self, filename, data)

    monkeypatch.setattr(ZipLogFile, "_zip_writestr", recording)

    recorder, spec = await _start_eval_recorder(tmp_path)
    sample = _sample()
    with _history(tmp_path) as history:
        await recorder.log_sample_streaming(spec, sample, history)
    await _finish_eval(recorder, spec)

    # positive controls, so the guard can't pass vacuously: the spy did
    # record the non-sample members, and the streamed sample itself landed
    assert written, "spy recorded no writes at all: _zip_writestr patch inert"
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))
    assert log.samples is not None
    assert len(log.samples[0].events) == 1

    assert _sample_filename(sample.id, sample.epoch) not in written, (
        f"sample entry written via monolithic writestr: {written}"
    )


@pytest.mark.anyio
async def test_streamed_sample_entry_relog_supersedes_with_no_warning(
    tmp_path: Path,
) -> None:
    """A re-logged (id, epoch) supersedes cleanly with no zipfile warning."""
    recorder, spec = await _start_eval_recorder(tmp_path)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with _history(tmp_path, name="h1") as history:
            await recorder.log_sample_streaming(
                spec, _sample().model_copy(update={"target": "stale"}), history
            )
        with _history(tmp_path, name="h2") as history:
            await recorder.log_sample_streaming(spec, _sample(), history)
    # scoped to zipfile's duplicate-member warning: promoting *all* warnings
    # to errors would fail on unrelated third-party deprecations
    assert not [w for w in caught if "Duplicate name" in str(w.message)]

    await _finish_eval(recorder, spec)
    log = await read_eval_log_async(str(tmp_path / "streaming.eval"))

    assert log.samples is not None and len(log.samples) == 1
    assert log.samples[0].target == "answer"


@pytest.mark.anyio
async def test_zip_open_write_restores_warning_filters_before_yield(
    tmp_path: Path,
) -> None:
    """The duplicate-name suppression must not span the open entry's lifetime.

    ``warnings.catch_warnings`` mutates process-global filter state; holding
    it while the entry is open spans every chunk checkpoint of the streamed
    write, letting concurrent tasks (e.g. two eval_set tasks, each with its
    own ``ZipLogFile``) run under -- or clobber -- the mutated filters. The
    warning is emitted by ``ZipFile.open`` itself, so the suppression only
    needs to wrap that call.
    """
    recorder, spec = await _start_eval_recorder(tmp_path)
    zip_log = recorder.data[recorder._log_file_key(spec)]

    filters_before = warnings.filters
    with zip_log._zip_open_write("samples/test.json") as stream:
        assert warnings.filters is filters_before, (
            "global warnings filters mutated while the zip entry is open"
        )
        stream.write(b"{}")


@contextlib.contextmanager
def _registered_hook(name: str, hook_class: type[Hooks]) -> Generator[None, None, None]:
    """Register `hook_class` under `name` for the duration of the block."""
    hooks(name, description=f"{name}-description")(hook_class)
    try:
        yield
    finally:
        del _registry[f"hooks:{name}"]


class _FullSampleHook(Hooks):
    pass


class _OptedOutHook(Hooks):
    def needs_full_sample(self) -> bool:
        return False


class _DisabledFullSampleHook(Hooks):
    """Disabled hook that would need a full sample (the default) if enabled."""

    def enabled(self) -> bool:
        return False


@solver
def _attachment_emitting_solver(n: int = 4) -> Solver:
    """Emits enough transcript events to exceed a resident_tail of 1.

    Each event carries >100 chars of unique content so realtime condensing
    turns it into an attachment, letting callers assert attachment integrity
    in the written log non-vacuously. Registered at module level (and named
    distinctly from test_hooks.py's ``_emitting_solver``): ``@solver``
    registers by function name in the global registry, so a per-call
    decoration would re-register on every use.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for i in range(n):
            transcript().info({"i": i, "content": f"{i} {_long_content()}"})
        return state

    return solve


Consumer = Literal[
    "none",
    "hook_full",
    "hook_opted_out",
    "hook_disabled",
    "scanner",
    "task_source",
    "sample_feed",
]


def _drive_evicted_eval(consumer: Consumer, log_dir: str) -> None:
    """Run a one-sample eval whose transcript is bounded-evicted.

    `consumer` selects which finalization consumer (if any) is wired up,
    mirroring the branches the `materialize_full_sample` check in `task_run_sample`
    covers: a hook (registered by the caller around this call), a scanner, a
    `TaskSource`, or a `SampleSource`.
    """
    task = Task(
        dataset=[Sample(input="question", target="answer")],
        solver=[_attachment_emitting_solver()],
    )

    if consumer == "scanner":
        pytest.importorskip("inspect_scout")
        from inspect_scout import Result, Transcript
        from inspect_scout import scanner as scout_scanner

        @scout_scanner(messages="all")
        def _echo_scanner() -> Callable[[Transcript], Awaitable[Result]]:
            async def scan(transcript: Transcript) -> Result:
                return Result(value="ok")

            return scan

        eval(
            task,
            scanner=[_echo_scanner()],
            model="mockllm/model",
            log_dir=log_dir,
            display="none",
        )
    elif consumer == "task_source":

        class _TaskSourceStub(TaskSource):
            def initial_tasks(self) -> list[Task]:
                return [task]

        eval(_TaskSourceStub(), model="mockllm/model", log_dir=log_dir, display="none")
    elif consumer == "sample_feed":

        class _SampleSourceStub(SampleSource):
            def initial_samples(self) -> list[Sample]:
                return [Sample(input="question", target="answer")]

        eval(
            Task(dataset=_SampleSourceStub(), solver=[_attachment_emitting_solver()]),
            model="mockllm/model",
            log_dir=log_dir,
            display="none",
        )
    elif (
        consumer == "none"
        or consumer == "hook_full"
        or consumer == "hook_opted_out"
        or consumer == "hook_disabled"
    ):
        eval(task, model="mockllm/model", log_dir=log_dir, display="none")
    else:
        assert_never(consumer)


@pytest.mark.parametrize(
    ("consumer", "expect_materialization"),
    [
        ("none", False),
        ("hook_full", True),
        ("hook_opted_out", False),
        ("hook_disabled", False),
        ("scanner", True),
        ("task_source", True),
        ("sample_feed", True),
    ],
)
def test_materialization_is_conditional(
    consumer: Consumer,
    expect_materialization: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_hooks_registry,
) -> None:
    """materialize_streaming_sample runs iff some consumer needs events.

    Drives a one-sample eval whose transcript is bounded-evicted
    (DEFAULT_RESIDENT_TAIL patched to 1) for each finalization consumer kind,
    and counts calls to materialize_streaming_sample. A plain `def` test:
    `eval()` manages its own event loop and cannot be called from `async def`.

    `isolated_hooks_registry` makes every row deterministic: the negative
    rows assert that *no* enabled hook needs a full sample, which any
    installed extension's entry-point hook would otherwise flip.
    """
    import inspect_ai._eval.task.run as run_module

    calls = {"n": 0}

    def counting(sample: EvalSample, history: SampleHistory) -> EvalSample:
        calls["n"] += 1
        return materialize_streaming_sample(sample, history)

    monkeypatch.setattr(run_module, "materialize_streaming_sample", counting)
    monkeypatch.setattr(run_module, "DEFAULT_RESIDENT_TAIL", 1)
    monkeypatch.setenv("INSPECT_TRANSCRIPT_BOUNDED", "true")

    hook_registration: contextlib.AbstractContextManager[None] = (
        contextlib.nullcontext()
    )
    if consumer == "hook_full":
        hook_registration = _registered_hook(
            "materialization_hook_full", _FullSampleHook
        )
    elif consumer == "hook_opted_out":
        hook_registration = _registered_hook(
            "materialization_hook_opted_out", _OptedOutHook
        )
    elif consumer == "hook_disabled":
        hook_registration = _registered_hook(
            "materialization_hook_disabled", _DisabledFullSampleHook
        )

    with hook_registration:
        _drive_evicted_eval(consumer, str(tmp_path))

    assert (calls["n"] > 0) == expect_materialization
    _assert_written_log_complete(tmp_path)


def _assert_written_log_complete(log_dir: Path, n_info_events: int = 4) -> None:
    """The written log is undamaged whether or not materialization ran.

    Reads the eval log back and asserts the evicted events all landed and
    that every `attachment://` ref in the sample resolves to attachment
    content — the user-visible contract that skipping the in-memory
    re-materialization does not alter what gets logged.
    """
    log = read_eval_log(str(next(log_dir.glob("*.eval"))))
    assert log.status == "success"
    assert log.samples is not None and len(log.samples) == 1
    sample = log.samples[0]

    info_indexes = [
        event.data["i"]
        for event in sample.events
        if isinstance(event, InfoEvent)
        and isinstance(event.data, dict)
        and "i" in event.data
    ]
    assert info_indexes == list(range(n_info_events))

    refs = set(re.findall(r"attachment://(\w+)", sample.model_dump_json()))
    assert refs, "expected condensed event content to produce attachment refs"
    assert refs <= set(sample.attachments), "dangling attachment ref in written log"
    assert all(sample.attachments[ref] for ref in refs)
